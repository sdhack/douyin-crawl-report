# -*- coding: utf-8 -*-
"""视频抽帧：用 PyAV 解码，绕开系统 ffmpeg 精简版无图片编码器的问题。
用法: python tools/extract_frames.py --root <工作根> --account <slug> [--fps 1]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 nutelande")
    ap.add_argument("--fps", type=int, default=1, help="抽帧频率（帧/秒），精校抽帧默认 1")
    a = ap.parse_args()

    vd = os.path.join(a.root, "videos", a.account)
    fd = os.path.join(a.root, "video-analysis", a.account, "frames")
    total = 0
    for mp4 in sorted(glob.glob(os.path.join(vd, "*.mp4"))):
        aid = os.path.splitext(os.path.basename(mp4))[0]
        n = extract(mp4, os.path.join(fd, aid), a.fps)
        total += n
        print(f"{aid}: {n} 帧")
    print(f"\n[完成] {len(glob.glob(os.path.join(vd, '*.mp4')))} 视频，共 {total} 帧")


if __name__ == "__main__":
    main()