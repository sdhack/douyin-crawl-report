# -*- coding: utf-8 -*-
"""口播转写：faster-whisper，GPU 优先（float16）多 worker 并行 + 断点续传。
CPU/GPU 自动择优：有 CUDA 用 cuda/float16（约快 10x），否则 cpu/int8。
用法: python tools/transcribe.py --root <工作根> --account <slug>
      [--model large-v3] [--device auto] [--compute auto] [--workers N]
依赖: pip 安装 faster-whisper, ctranslate2；GPU 需 nvidia-cublas-cu12（脚本自动定位并加入 PATH）
输出: <root>/transcript/<account>/{aweme_id}.txt | .json
"""
import argparse, os, sys, time, glob, json
import concurrent.futures


def find_cublas():
    """ctranslate2(自制 CUDA12) 需要 cublas64_12.dll；定位 pip 装目录并提前 PATH。"""
    import glob as g
    for base in list(sys.path):
        for p in g.glob(os.path.join(base, "nvidia", "cublas*", "bin")):
            if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
                return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 nutelande")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto", help="auto/cuda/cpu")
    ap.add_argument("--compute", default="auto", help="auto/float16/int8/float32")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("TXP_WORKERS", "2")))
    a = ap.parse_args()

    find_cublas()
    import ctranslate2
    has_cuda = ctranslate2.get_cuda_device_count() > 0
    device = "cuda" if (a.device == "auto" and has_cuda) else ("cpu" if a.device == "auto" else a.device)
    compute = "float16" if (a.compute == "auto" and device == "cuda") else ("int8" if a.compute == "auto" else a.compute)
    print(f"[env] cuda_count={has_cuda} -> device={device}, compute={compute}（择优结果）")

    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device=device, compute_type=compute)

    vd = os.path.join(a.root, "videos", a.account)
    od = os.path.join(a.root, "transcript", a.account)
    os.makedirs(od, exist_ok=True)

    def one(mp4):
        aid = os.path.splitext(os.path.basename(mp4))[0]
        tp = os.path.join(od, aid + ".txt")
        jp = os.path.join(od, aid + ".json")
        if os.path.exists(tp) and os.path.exists(jp):
            return aid, "skip"
        t0 = time.time()
        try:
            segs, info = model.transcribe(
                mp4, language="zh", beam_size=5, vad_filter=True,
                initial_prompt="以下是一段抖音口播视频的普通话转写，请准确识别产品专业名词、数字与品牌名。",
            )
            lines, sl = [], []
            for s in segs:
                lines.append(f"[{s.start:06.2f} - {s.end:06.2f}] {s.text.strip()}")
                sl.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
            with open(tp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            with open(jp, "w", encoding="utf-8") as f:
                json.dump({
                    "aweme_id": aid, "language": info.language,
                    "language_probability": round(float(info.language_probability), 3),
                    "duration": round(float(info.duration), 2), "segments": sl,
                }, f, ensure_ascii=False, indent=2)
            return aid, f"ok {len(sl)}segs {time.time()-t0:.1f}s"
        except Exception as e:
            return aid, f"ERR {str(e)[:80]}"

    mp4s = sorted(glob.glob(os.path.join(vd, "*.mp4")))
    print(f"[start] {len(mp4s)} videos -> {od} ({device}, {a.workers} workers)")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, mp): mp for mp in mp4s}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            aid, note = fu.result()
            results.append(note)
            print(f"  [{i}/{len(mp4s)}] {aid}: {note}")
    errs = [r for r in results if r.startswith("ERR")]
    skips = [r for r in results if r == "skip"]
    print(f"[done] total={len(results)} ok={len(results)-len(errs)-len(skips)} skip={len(skips)} err={len(errs)}")
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()