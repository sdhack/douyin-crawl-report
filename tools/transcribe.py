# -*- coding: utf-8 -*-
"""口播转写：直接下载并使用抓取 JSON 中的 music_download_url。
- CPU/GPU 自动择优：有 CUDA 用 cuda/float16（约快 10x），否则 cpu/int8。
- 全部产物已存在时跳过模型加载（省冷启动约 5s）。
- 可选术语纠错映射 --map <json>：{误词: 正词}，转写后自动订正专业名词误识（提质）。
用法: python tools/transcribe.py --root <工作根> --account <slug>
      [--model large-v3] [--device auto] [--compute auto] [--workers N] [--map <term_map.json>]
依赖: pip 安装 faster-whisper, ctranslate2; GPU 需 nvidia-cublas-cu12（脚本自动定位并加入 PATH）
输入：`video-analysis/<account>/manifest.json` 的 music_url，缓存至 `bgm/<account>/audio/`。
不从 MP4 分离音频；低置信度结果标记 needs_visual_review，供后续结合画面字幕核验。
输出: <root>/transcript/<account>/{aweme_id}.txt | .json
"""
import argparse, os, sys, time, glob, json
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402
from audio_source import cached_audio, manifest_items  # noqa: E402


def find_cublas():
    """ctranslate2(自制 CUDA12) 需要 cublas64_12.dll；定位 pip 装目录并提前 PATH。"""
    import glob as g
    for base in list(sys.path):
        for p in g.glob(os.path.join(base, "nvidia", "cublas*", "bin")):
            if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                return


def load_terms(path):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k and v and k != v}
    except Exception as e:
        print(f"[warn] --map 解析失败，忽略: {e}", flush=True)
        return None


def correct(text, terms):
    """按术语映射订正误识；terms 为 None 时原样返回。"""
    if not terms or not text:
        return text
    for k, v in terms.items():
        text = text.replace(k, v)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 myaccount")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto", help="auto/cuda/cpu")
    ap.add_argument("--compute", default="auto", help="auto/float16/int8/float32")
    ap.add_argument("--workers", type=int, default=None,
                    help="转写 worker 数（缺省按机器配置自动调度，GPU 宜少）")
    ap.add_argument("--map", default=None, help="术语纠错映射 json：{误词: 正词}")
    a = ap.parse_args()

    find_cublas()
    import ctranslate2

    audio_dir = os.path.join(a.root, "bgm", a.account, "audio")
    od = os.path.join(a.root, "transcript", a.account)
    os.makedirs(od, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    try:
        inputs = manifest_items(a.root, a.account)
    except Exception as e:
        sys.exit(f"[ERR] {e}")

    def prod_exists(aid):
        return os.path.exists(os.path.join(od, aid + ".txt")) and os.path.exists(os.path.join(od, aid + ".json"))

    terms = load_terms(a.map)

    def rewrite_corrected(tp, jp, terms):
        """对已产成 .txt/.json 的文本层做术语订正；有改动返回 True。"""
        try:
            with open(tp, encoding="utf-8") as f:
                txt = f.read()
            if not any(k in txt for k in terms):
                return False
            with open(tp, "w", encoding="utf-8") as f:
                f.write(correct(txt, terms))
            data = json.load(open(jp, encoding="utf-8"))
            for seg in data.get("segments", []):
                seg["text"] = correct(seg.get("text", ""), terms)
            json.dump(data, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def prod_missing(item):
        return not prod_exists(item[0])

    has_cuda = ctranslate2.get_cuda_device_count() > 0

    # 快检：全部已产成 → 不解码模型；有 --map 仅对已有产物就地订正文本层
    if all(not prod_missing(m) for m in inputs):
        if terms:
            n_fix = sum(rewrite_corrected(os.path.join(od, m[0] + ".txt"),
                                          os.path.join(od, m[0] + ".json"),
                                          terms) for m in inputs)
            print(f"[skip-all] {len(inputs)} 个视频均已产成，按 --map 订正 {n_fix} 个 | {probe.snapshot(has_cuda)}", flush=True)
        else:
            print(f"[skip-all] {len(inputs)} 个视频均已产成，跳过模型加载与转写 | {probe.snapshot(has_cuda)}", flush=True)
        return

    pending = [m for m in inputs if prod_missing(m)]
    device = "cuda" if (a.device == "auto" and has_cuda) else ("cpu" if a.device == "auto" else a.device)
    compute = "float16" if (a.compute == "auto" and device == "cuda") else ("int8" if a.compute == "auto" else a.compute)
    print(f"[env] cuda_count={has_cuda}", flush=True)
    w = a.workers or probe.transcribe_workers(has_cuda)
    print(f"[资源] {probe.snapshot(has_cuda)} -> device={device}/{compute}，转写worker数={w}", flush=True)

    from faster_whisper import WhisperModel

    def load_model(path, dev, comp):
        """技能承诺的自动降级：float16 不被卡/CUDA 后端支持时按
        int8_float32 -> CPU int8 逐级回退（此前从未实现，实测直接 ValueError 崩溃）"""
        try:
            return WhisperModel(path, device=dev, compute_type=comp), dev, comp
        except (ValueError, RuntimeError, OSError) as e:
            if dev == "cuda" and comp == "float16":
                print(f"[warn] float16 不受支持({str(e)[:60]})，降级 int8_float32 重试", flush=True)
                try:
                    return WhisperModel(path, device="cuda", compute_type="int8_float32"), "cuda", "int8_float32"
                except (ValueError, RuntimeError, OSError):
                    pass
            if dev == "cuda":
                print("[warn] CUDA 后端不可用，回退 CPU int8", flush=True)
                return WhisperModel(path, device="cpu", compute_type="int8"), "cpu", "int8"
            raise

    model, device, compute = load_model(a.model, device, compute)
    print(f"[model] 实际生效 device={device}/{compute}", flush=True)
    if terms:
        print(f"[map] 术语纠错映射已启用：{len(terms)} 项", flush=True)

    def one(item):
        aid, url = item
        tp = os.path.join(od, aid + ".txt")
        jp = os.path.join(od, aid + ".json")
        t0 = time.time()
        try:
            audio_path = cached_audio(a.root, a.account, aid, url)
            segs, info = model.transcribe(
                audio_path, language="zh", beam_size=5, vad_filter=True,
                initial_prompt="以下是一段抖音口播视频的普通话转写，请准确识别产品专业名词、数字与品牌名。",
            )
            lines, sl, probs = [], [], []
            for s in segs:
                t = correct(s.text.strip(), terms)
                lines.append(f"[{s.start:06.2f} - {s.end:06.2f}] {t}")
                sl.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": t})
                probs.append(float(s.avg_logprob))
            with open(tp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            with open(jp, "w", encoding="utf-8") as f:
                json.dump({
                    "aweme_id": aid, "language": info.language,
                    "language_probability": round(float(info.language_probability), 3),
                    "duration": round(float(info.duration), 2), "segments": sl,
                    "source": "music_download_url",
                    "audio_path": os.path.relpath(audio_path, a.root).replace(os.sep, "/"),
                    "avg_logprob": round(sum(probs) / len(probs), 3) if probs else None,
                    "needs_visual_review": bool(float(info.language_probability) < 0.80 or not sl or
                                                (probs and sum(probs) / len(probs) < -0.8)),
                }, f, ensure_ascii=False, indent=2)
            return aid, f"ok {len(sl)}segs {time.time()-t0:.1f}s"
        except Exception as e:
            return aid, f"ERR {str(e)[:80]}"

    print(f"[start] {len(pending)} videos -> {od} ({device}, {w} workers)", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=w) as ex:
        futs = {ex.submit(one, item): item for item in pending}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            aid, note = fu.result()
            results.append(note)
            print(f"  [{i}/{len(pending)}] {aid}: {note}", flush=True)
    errs = [r for r in results if r.startswith("ERR")]
    print(f"[done] total={len(pending)} ok={len(pending)-len(errs)} err={len(errs)}", flush=True)
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()
