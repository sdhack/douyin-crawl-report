# -*- coding: utf-8 -*-
"""视频抽帧：用 PyAV 解码，绕开系统 ffmpeg 精简版无图片编码器的问题。
多进程按视频并行（CPU-bound，接近线性加速）。
用法: python tools/extract_frames.py --root <工作根> --account <slug> [--fps 1] [--workers N]
输出: <root>/video-analysis/<account>/frames/<aweme_id>/*.jpg
"""
import argparse, av, os, glob


def extract(mp4, out_dir, fps):
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.jpg")):
        os.remove(old)
    n = 0
    try:
        c = av.open(mp4)
        video = c.streams.video[0]
        rate = float(video.average_rate or 30)
        if rate <= 0:
            rate = 30
        step = int(round(rate / fps))
        idx = 0
        for frame in c.decode(video=0):
            if idx % step == 0:
                frame.to_image().save(os.path.join(out_dir, f"{n+1:03d}.jpg"), "JPEG", quality=90)
                n += 1
            idx += 1
        c.close()
    except Exception as e:
        print(f"  {mp4}: ERR {str(e)[:80]}")
        return 0
    return n


def _worker(args):
    mp4, outdir, fps = args
    aid = os.path.splitext(os.path.basename(mp4))[0]
    n = extract(mp4, os.path.join(outdir, aid), fps)
    return aid, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 nutelande")
    ap.add_argument("--fps", type=int, default=1, help="抽帧频率（帧/秒），精校抽帧默认 1")
    ap.add_argument("--workers", type=int, default=min(os.cpu_count() or 2, 4),
                    help="并行进程数（默认 min(CPU核,4)）")
    a = ap.parse_args()

    vd = os.path.join(a.root, "videos", a.account)
    fd = os.path.join(a.root, "video-analysis", a.account, "frames")
    tasks = [(mp4, fd, a.fps) for mp4 in sorted(glob.glob(os.path.join(vd, "*.mp4")))]

    from multiprocessing import Pool
    total, n0 = 0, len(tasks)
    with Pool(a.workers) as pool:
        for done, (aid, n) in enumerate(pool.imap_unordered(_worker, tasks), 1):
            total += n
            print(f"  [{done}/{n0}] {aid}: {n} 帧")
    print(f"\n[完成] {n0} 视频，共 {total} 帧（进程数 {a.workers}）")


if __name__ == "__main__":
    main()