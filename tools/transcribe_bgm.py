# -*- coding: utf-8 -*-
"""BGM 归档（风格 + 文案参考）：faster-whisper large-v3 识别音频 + PyAV 能量包络启发式。

固定使用 large-v3 模型（与口播转写一致，模型已缓存到项目 models_cache，免联网下载）。

适用：快消/带货视频对标报告做「BGM 选用策略」维度。每条视频输出:
  bgm_level  : none / light / full（背景音乐垫底强度，基于低频能量占比）
  vocal      : speech / singing / none（人声性质）
  energy_var : 响度起伏（叙事强弱）
  mood       : 启发式情绪标签（平静铺垫 / 明快节奏 / 强节奏 / 叙事起伏）
  bgm_text   : BGM 可识别的歌词/元素文本（作文案参考线索）
说明：这是轻量启发式归档，用于报告风格维度统计与文案参考；精确曲目识别需额外音乐检索模型。

用法: python tools/transcribe_bgm.py --root <工作根> --account <slug>
      [--device auto] [--compute auto] [--workers N]
输出: <root>/bgm/<account>/{aweme_id}.json + <root>/bgm/<account>/_manifest.json
依赖: faster-whisper, av, numpy; GPU 需 nvidia-cublas-cu12（脚本自动定位）
"""
import argparse, os, sys, time, glob, json
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402

try:
    import numpy as np
except Exception:
    sys.exit("[ERR] 需 numpy：安装分析运行库后重试")

SR = 16000
FLEN = int(0.025 * SR)   # 25ms 帧
FSTEP = int(0.010 * SR)  # 10ms hop
LOWF = 200.0             # 低频阈值 Hz（BGM 通常持续低频垫底）


def find_cublas():
    import glob as g
    for base in list(sys.path):
        for p in g.glob(os.path.join(base, "nvidia", "cublas*", "bin")):
            if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                return


def _decoded(mp4):
    try:
        import av
    except Exception:
        sys.exit("[ERR] 需 av：分析运行库未装，先 pip install av")
    container = av.open(mp4)
    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        container.close()
        return None
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
    out = []
    for frame in container.decode(stream):
        for rf in resampler.resample(frame):
            out.append(rf.to_ndarray().reshape(-1))
    container.close()
    if not out:
        return None
    return np.concatenate(out).astype(np.float32) / 32768.0


def _rms_frames(x):
    """滑动帧 RMS：返回 (rms 序列, 均值, 标准差, 静音占比)。"""
    n_frames = max(1, (len(x) - FLEN) // FSTEP + 1)
    idx = np.arange(n_frames) * FSTEP
    rms = np.zeros(n_frames)
    for i, s in enumerate(idx):
        seg = x[s:s + FLEN]
        rms[i] = float(np.sqrt((seg ** 2).mean())) if len(seg) else 0.0
    return rms, float(rms.mean()), float(rms.std()), float((rms < 0.01).mean())


def _lowfreq_ratio(x):
    """低频(<200Hz)能量占比：>0.5 视为存在持续低频垫底(BGM)。"""
    x = x[: int(SR * 30)] if len(x) > int(SR * 30) else x     # 取样前30s省时
    if len(x) < 1024:
        return 0.0
    nfft = 2048
    a = np.array_split(x, max(1, len(x) // nfft))
    low, tot = 0.0, 1e-9
    for blk in a[:60]:
        sp = np.abs(np.fft.rfft(blk * np.hanning(len(blk))))
        freqs = np.fft.rfftfreq(len(blk), 1.0 / SR)
        low += float(sp[freqs < LOWF].sum())
        tot += float(sp.sum())
    return low / tot if tot else 0.0


def classify(x, txt, avg_prob):
    """由音频包络 + 转写着启发式归档。"""
    if x is None:
        return {"bgm_level": "none", "vocal": "none", "mood": "silent",
                "energy": 0.0, "energy_var": 0.0, "silence": 1.0}
    _, emean, evar, sil = _rms_frames(x)
    lfe = _lowfreq_ratio(x)

    # vocal：能转出文本且似语音
    has_speech = bool(txt and len(txt) >= 8)
    # BGM 强度：低频占比高 或 响度平稳而非常规纯语音停顿
    if lfe >= 0.55:
        bgm = "full"
    elif lfe >= 0.35:
        bgm = "light" if emean < 0.25 else "full"
    else:
        bgm = "light" if (has_speech and evar < 0.10 and emean > 0.15) else "none"

    vocal = "speech" if has_speech else ("singing" if avg_prob and avg_prob < 0.6 else "none")

    # mood 启发式
    if bgm == "none" and vocal == "none":
        mood = "静默/无BGM"
    elif emean >= 0.32:
        mood = "强节奏/重鼓点" if evar < 0.12 else "明快节奏"
    elif emean <= 0.10:
        mood = "平静铺垫"
    elif evar >= 0.10:
        mood = "叙事起伏"
    else:
        mood = "明快节奏"

    return {
        "bgm_level": bgm, "vocal": vocal, "mood": mood,
        "energy": round(emean, 4), "energy_var": round(evar, 4),
        "silence": round(sil, 3), "lfe_ratio": round(lfe, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--model", default="large-v3", help="固定 large-v3（与口播转写一致，已缓存免联网）")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute", default="auto")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()

    find_cublas()
    try:
        import ctranslate2
    except Exception:
        ctranslate2 = None
    has_cuda = bool(ctranslate2 is not None and ctranslate2.get_cuda_device_count() > 0)

    vd = os.path.join(a.root, "videos", a.account)
    od = os.path.join(a.root, "bgm", a.account)
    os.makedirs(od, exist_ok=True)
    mp4s = sorted(glob.glob(os.path.join(vd, "*.mp4")))
    if not mp4s:
        print(f"[warn] 未找到视频: {vd}，无 BGM 可分析")
        return

    def done(aid):
        return os.path.exists(os.path.join(od, aid + ".json"))

    if all(done(os.path.splitext(os.path.basename(m))[0]) for m in mp4s):
        print(f"[skip-all] {len(mp4s)} 个 BGM 产物均已产成，跳过 | {probe.snapshot(has_cuda)}")
        return

    device = "cuda" if (a.device == "auto" and has_cuda) else ("cpu" if a.device == "auto" else a.device)
    compute = "float16" if (a.compute == "auto" and device == "cuda") else ("int8" if a.compute == "auto" else a.compute)
    w = a.workers or probe.transcribe_workers(has_cuda)
    print(f"[env] cuda_count={has_cuda} | {probe.snapshot(has_cuda)} -> device={device}/{compute}, workers={w}")

    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device=device, compute_type=compute)

    def one(mp4):
        aid = os.path.splitext(os.path.basename(mp4))[0]
        if done(aid):
            return aid, "skip"
        t0 = time.time()
        try:
            x = _decoded(mp4)
            txt, avg = "", None
            try:
                segs, info = model.transcribe(mp4, language=None, vad_filter=False,
                                              beam_size=5, condition_on_previous_text=False)
                segs = list(segs)
                txt = "".join(s.text.strip() for s in segs)
                avg = float(sum(s.avg_logprob for s in segs) / len(segs)) if segs else None
            except Exception as e:
                txt, avg = "", None
            meta = classify(x, txt, avg)
            meta.update({"aweme_id": aid, "duration_sec": round((len(x) / SR) if x is not None else 0, 1),
                         "bgm_text": txt[:200], "lang": "zh-hint"})
            jp = os.path.join(od, aid + ".json")
            with open(jp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return aid, f"ok {meta['bgm_level']}/{meta['vocal']}/{meta['mood']} {time.time()-t0:.1f}s"
        except Exception as e:
            return aid, f"ERR {str(e)[:90]}"

    print(f"[start] {len(mp4s)} videos -> {od}")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futs = {ex.submit(one, m): m for m in mp4s}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            aid, note = fu.result()
            results.append(note)
            print(f"  [{i}/{len(mp4s)}] {aid}: {note}")

    # 聚合 manifest
    agg = {"by_bgm": {}, "by_mood": {}, "by_vocal": {}, "n": len(results)}
    records = []
    for m in mp4s:
        jp = os.path.join(od, os.path.splitext(os.path.basename(m))[0] + ".json")
        if os.path.exists(jp):
            records.append(json.load(open(jp, encoding="utf-8")))
    for r in records:
        agg["by_bgm"][r["bgm_level"]] = agg["by_bgm"].get(r["bgm_level"], 0) + 1
        agg["by_mood"][r["mood"]] = agg["by_mood"].get(r["mood"], 0) + 1
        agg["by_vocal"][r["vocal"]] = agg["by_vocal"].get(r["vocal"], 0) + 1
    manifest_p = os.path.join(od, "_manifest.json")
    json.dump(agg, open(manifest_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    errs = [r for r in results if r.startswith("ERR")]
    skips = [r for r in results if r == "skip"]
    print("=" * 60)
    print(f"[聚合] {json.dumps(agg, ensure_ascii=False)}")
    print(f"[done] total={len(results)} ok={len(results)-len(errs)-len(skips)} skip={len(skips)} err={len(errs)}")
    print(f"[manifest] {manifest_p}")
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()