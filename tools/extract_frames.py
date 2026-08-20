# -*- coding: utf-8 -*-
"""自适应画面抽帧：基础采样 + 镜头突变 + 低置信度视频加密采样。
多进程按视频并行（CPU-bound，接近线性加速）。
用法: python tools/extract_frames.py --root <工作根> --account <slug> [--fps 1] [--workers N]
输出: <root>/video-analysis/<account>/frames/<aweme_id>/*.jpg
"""
import argparse, av, os, glob, sys, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402


def extract(mp4, out_dir, fps, review_fps, scene_threshold, needs_review, min_frames):
    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "frames.json")
    config = {"fps": fps, "review_fps": review_fps, "scene_threshold": scene_threshold, "min_frames": min_frames,
              "needs_visual_review": needs_review, "source_mtime": os.path.getmtime(mp4)}
    if os.path.exists(meta_path):
        try:
            old = json.load(open(meta_path, encoding="utf-8"))
            if old.get("completed") and old.get("config") == config and all(
                    os.path.exists(os.path.join(out_dir, r["file"])) for r in old.get("frames", [])):
                return len(old.get("frames", []))
        except Exception:
            pass
    for old in glob.glob(os.path.join(out_dir, "*.jpg")):
        os.remove(old)
    n, records, prev_hist, last_saved = 0, [], None, -999.0
    try:
        c = av.open(mp4)
        video = c.streams.video[0]
        rate = float(video.average_rate or 30)
        if rate <= 0:
            rate = 30
        sample_fps = review_fps if needs_review else fps
        total_frames = int(video.frames or 0)
        regular_step = max(1, int(round(rate / sample_fps)))
        coverage_step = max(1, total_frames // min_frames) if total_frames else regular_step
        step = min(regular_step, coverage_step)
        idx = 0
        for frame in c.decode(video=0):
            # frame.time=0.0 是合法首帧时间戳，须显式判 None（or 会把 0 当缺失回退 idx/rate）
            t = float(frame.time) if frame.time is not None else idx / rate
            img = frame.to_image()
            thumb = np.asarray(img.resize((64, 36)).convert("L"), dtype=np.float32)
            hist, _ = np.histogram(thumb, bins=32, range=(0, 256), density=True)
            scene_score = float(np.abs(hist - prev_hist).sum() / 2) if prev_hist is not None else 0.0
            intro_due = t < 3 and idx % max(1, int(round(rate / 3))) == 0
            base_due = idx % step == 0 or intro_due
            scene_due = scene_score >= scene_threshold and t - last_saved >= 0.20
            if base_due or scene_due:
                name = f"{n+1:04d}.jpg"
                img.save(os.path.join(out_dir, name), "JPEG", quality=90)
                n += 1
                last_saved = t
                reason = "scene" if scene_due and not base_due else ("review" if needs_review else ("intro" if intro_due else "base"))
                records.append({"file": name, "timestamp": round(t, 3), "reason": reason,
                                "scene_score": round(scene_score, 4), "brightness": round(float(thumb.mean()), 2),
                                "sharpness": round(float(np.var(np.diff(thumb, axis=1))), 2)})
            prev_hist = hist
            idx += 1
        c.close()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"adaptive": True, "completed": True, "config": config,
                       "needs_visual_review": needs_review, "frames": records}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  {mp4}: ERR {str(e)[:80]}", flush=True)
        return -1  # 解码失败须与合法 0 帧区分，供 main 聚合后 fail-loud
    return n


def _worker(args):
    mp4, outdir, fps, review_fps, threshold, review_ids, min_frames = args
    aid = os.path.splitext(os.path.basename(mp4))[0]
    n = extract(mp4, os.path.join(outdir, aid), fps, review_fps, threshold, aid in review_ids, min_frames)
    return aid, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 myaccount")
    ap.add_argument("--fps", type=int, default=1, help="抽帧频率（帧/秒），精校抽帧默认 1")
    ap.add_argument("--review-fps", type=int, default=5, help="低置信度转写视频的加密抽帧频率")
    ap.add_argument("--scene-threshold", type=float, default=0.18, help="镜头突变直方图阈值")
    ap.add_argument("--min-frames", type=int, default=12, help="每视频最低均匀覆盖采样点（默认12）")
    ap.add_argument("--workers", type=int, default=None,
                    help="并行进程数（缺省按机器配置自动调度 min(核,4) 且受可用内存约束）")
    a = ap.parse_args()
    if a.fps <= 0 or a.review_fps <= 0:
        sys.exit("[ERR] --fps / --review-fps 必须为正数（0 会触发除零并被吞掉，视频静默 0 帧）")

    w = a.workers or probe.frame_workers()
    print(f"[资源] {probe.snapshot(probe.has_gpu())} -> 抽帧进程数={w}", flush=True)

    vd = os.path.join(a.root, "videos", a.account)
    fd = os.path.join(a.root, "video-analysis", a.account, "frames")
    review_ids = set()
    for jp in glob.glob(os.path.join(a.root, "transcript", a.account, "*.json")):
        try:
            if json.load(open(jp, encoding="utf-8")).get("needs_visual_review"):
                review_ids.add(os.path.splitext(os.path.basename(jp))[0])
        except Exception:
            pass
    tasks = [(mp4, fd, a.fps, a.review_fps, a.scene_threshold, review_ids, a.min_frames)
             for mp4 in sorted(glob.glob(os.path.join(vd, "*.mp4")))]

    from multiprocessing import Pool
    total, n0, failed = 0, len(tasks), []
    with Pool(w) as pool:
        for done, (aid, n) in enumerate(pool.imap_unordered(_worker, tasks), 1):
            if n < 0:
                failed.append(aid)
                print(f"  [{done}/{n0}] {aid}: ERR 解码失败", flush=True)
            else:
                total += n
                print(f"  [{done}/{n0}] {aid}: {n} 帧", flush=True)
    print(f"\n[完成] {n0} 视频，共 {total} 帧（进程数 {w}）", flush=True)
    if failed:
        # 下载截断的 MP4 会让解码中途崩（jpg 落一半、无 frames.json），此前静默 exit 0，
        # 下游逐帧分析把该视频当 0 帧吞掉；必须 fail-loud 让用户重下再补抽
        print(f"[ERR] {len(failed)} 个视频解码失败（无 frames.json，下游会整体跳过）：", flush=True)
        for aid in sorted(failed):
            print(f"      {aid}", flush=True)
        print("      处置：删除对应 videos/<account>/<aid>.mp4 后重跑 download.py，再重跑本工具（断点续抽）", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
