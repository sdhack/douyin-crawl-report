# -*- coding: utf-8 -*-
"""自适应画面抽帧：GPU 优先的两阶段代理扫描与高清候选帧提取。

第一阶段用 NVDEC + scale_cuda 读取 64x36 灰度代理帧，检测均匀采样、前三秒
3 FPS 以及镜头突变；第二阶段只提取候选时间点的高清帧。GPU 不可用或单个视频
失败时自动回退到 PyAV CPU。视频产物写入 frames.json，图文产物契约保持不变。
用法: python tools/extract_frames.py --root <工作根> --account <slug>
      [--fps 1] [--review-fps 5] [--device auto|cuda|cpu] [--max-frames 180]
"""
import argparse
import av
import glob
import json
import os
import shutil
import subprocess
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402


FRAME_SCHEMA_VERSION = 2
PROXY_W, PROXY_H = 64, 36


def _video_meta(mp4):
    """只读取容器元数据；真正的完整性校验在扫描/渲染阶段完成。"""
    try:
        c = av.open(mp4)
        video = c.streams.video[0]
        rate = float(video.average_rate or 30)
        if rate <= 0:
            rate = 30.0
        frames = int(video.frames or 0)
        duration = float(video.duration * video.time_base) if video.duration and video.time_base else 0.0
        width, height = int(video.width or 0), int(video.height or 0)
        c.close()
        if width <= 0 or height <= 0:
            raise ValueError("视频没有有效画面尺寸")
        return {"rate": rate, "frames": frames, "duration": duration,
                "width": width - width % 2, "height": height - height % 2}
    except Exception as e:
        raise RuntimeError(f"读取视频元数据失败: {e}") from e


def _hist_and_features(gray):
    gray = np.asarray(gray, dtype=np.float32).reshape(PROXY_H, PROXY_W)
    hist, _ = np.histogram(gray, bins=32, range=(0, 256), density=True)
    # 平均哈希用于去掉完全重复/极相似的代理帧；直方图用于过滤颜色/亮度相同的重复帧。
    yy = np.linspace(0, PROXY_H - 1, 8).astype(int)
    xx = np.linspace(0, PROXY_W - 1, 8).astype(int)
    small = gray[np.ix_(yy, xx)]
    phash = small >= small.mean()
    return hist, phash, gray


def _hamming(a, b):
    return int(np.count_nonzero(a != b))


def _review_intervals(info):
    """解析新旧转写标记。

    只有 segment 明确带置信度字段时才加密相应区间。旧 JSON 只有全局
    needs_visual_review 时不把整条视频变成 5 FPS，只保留基础采样并记录兼容模式。
    """
    if not info or not info.get("needs_visual_review"):
        return [], "none"
    segments = info.get("segments") or []
    intervals = []
    saw_confidence = False
    for seg in segments:
        keys = ("confidence", "avg_logprob", "language_probability", "probability")
        values = {k: seg.get(k) for k in keys if seg.get(k) is not None}
        if not values:
            continue
        saw_confidence = True
        if values.get("confidence") is not None:
            low = float(values["confidence"]) < 0.80
        elif values.get("probability") is not None:
            low = float(values["probability"]) < 0.80
        elif values.get("language_probability") is not None:
            low = float(values["language_probability"]) < 0.80
        else:
            low = float(values["avg_logprob"]) < -0.80
        if low:
            start = max(0.0, float(seg.get("start", 0.0)) - 0.35)
            end = max(start, float(seg.get("end", start + 0.5)) + 0.35)
            intervals.append((start, end))
    if not saw_confidence:
        return [], "global_only_no_interval"
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 0.25:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [(round(s, 3), round(e, 3)) for s, e in merged], "segment_confidence"


def _in_intervals(t, intervals):
    return any(start <= t <= end for start, end in intervals)


def _candidate(idx, t, score, reason, hist, phash, gray):
    return {"idx": idx, "timestamp": round(float(t), 3), "reason": reason,
            "scene_score": round(float(score), 4),
            "brightness": round(float(gray.mean()), 2),
            "sharpness": round(float(np.var(np.diff(gray, axis=1))), 2),
            "hist": hist, "phash": phash}


def _dedupe_candidates(candidates, min_interval):
    """感知哈希 + 直方图去重；基础覆盖点优先保留。"""
    candidates = sorted(candidates, key=lambda x: x["idx"])
    result = []
    for item in candidates:
        is_protected = item["reason"] in ("base", "intro")
        if result and item["timestamp"] - result[-1]["timestamp"] < min_interval and not is_protected:
            continue
        duplicate = False
        for old in reversed(result[-12:]):
            if item["timestamp"] - old["timestamp"] > 2.0:
                break
            if (_hamming(item["phash"], old["phash"]) <= 4 and
                    float(np.abs(item["hist"] - old["hist"]).sum()) <= 0.12):
                duplicate = True
                break
        if duplicate and not is_protected:
            continue
        result.append(item)
    return result


def _cap_candidates(candidates, max_frames):
    if len(candidates) <= max_frames:
        return candidates
    # 首先保留前三秒和高分镜头，再用均匀位置补足软上限。
    intro = [x for x in candidates if x["reason"] == "intro"]
    scenes = sorted((x for x in candidates if x["reason"] == "scene"),
                    key=lambda x: x["scene_score"], reverse=True)
    scene_budget = min(len(scenes), max(1, max_frames // 4))
    chosen = {x["idx"]: x for x in intro}
    for item in scenes[:scene_budget]:
        chosen[item["idx"]] = item
    remaining = [x for x in candidates if x["idx"] not in chosen]
    budget = max_frames - len(chosen)
    if budget > 0 and remaining:
        positions = np.linspace(0, len(remaining) - 1, min(budget, len(remaining)), dtype=int)
        for pos in positions:
            chosen[remaining[int(pos)]["idx"]] = remaining[int(pos)]
    return sorted(chosen.values(), key=lambda x: x["idx"])[:max_frames]


def _scan_cpu(mp4, meta, fps, review_fps, threshold, intervals, min_frames):
    candidates, prev_hist, idx = [], None, 0
    regular_step = max(1, int(round(meta["rate"] / fps)))
    coverage_step = max(1, meta["frames"] // min_frames) if meta["frames"] else regular_step
    step = min(regular_step, coverage_step)
    intro_step = max(1, int(round(meta["rate"] / 3)))
    review_step = max(1, int(round(meta["rate"] / review_fps)))
    c = av.open(mp4)
    try:
        for frame in c.decode(video=0):
            t = float(frame.time) if frame.time is not None else idx / meta["rate"]
            img = frame.to_image()
            gray = np.asarray(img.resize((PROXY_W, PROXY_H)).convert("L"), dtype=np.float32)
            hist, phash, gray = _hist_and_features(gray)
            score = float(np.abs(hist - prev_hist).sum() / 2) if prev_hist is not None else 0.0
            intro_due = t < 3.0 and idx % intro_step == 0
            review_due = bool(intervals and _in_intervals(t, intervals) and idx % review_step == 0)
            base_due = idx % step == 0
            scene_due = score >= threshold
            if base_due or intro_due or review_due or scene_due:
                reason = "scene" if scene_due and not (base_due or intro_due or review_due) else (
                    "review" if review_due else ("intro" if intro_due and not base_due else "base"))
                candidates.append(_candidate(idx, t, score, reason, hist, phash, gray))
            prev_hist = hist
            idx += 1
    finally:
        c.close()
    return candidates


def _run_gpu_proxy(mp4, meta, fps, review_fps, threshold, intervals, min_frames):
    ffmpeg = probe.ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
           "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", mp4,
           "-an", "-vf", f"scale_cuda={PROXY_W}:{PROXY_H},hwdownload,format=nv12,format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-vsync", "0", "pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    candidates, prev_hist, idx = [], None, 0
    regular_step = max(1, int(round(meta["rate"] / fps)))
    coverage_step = max(1, meta["frames"] // min_frames) if meta["frames"] else regular_step
    step = min(regular_step, coverage_step)
    intro_step = max(1, int(round(meta["rate"] / 3)))
    review_step = max(1, int(round(meta["rate"] / review_fps)))
    try:
        while True:
            raw = p.stdout.read(PROXY_W * PROXY_H)
            if not raw:
                break
            if len(raw) != PROXY_W * PROXY_H:
                raise RuntimeError("GPU 代理帧输出截断")
            hist, phash, gray = _hist_and_features(np.frombuffer(raw, dtype=np.uint8))
            t = idx / meta["rate"]
            score = float(np.abs(hist - prev_hist).sum() / 2) if prev_hist is not None else 0.0
            intro_due = t < 3.0 and idx % intro_step == 0
            review_due = bool(intervals and _in_intervals(t, intervals) and idx % review_step == 0)
            base_due = idx % step == 0
            scene_due = score >= threshold
            if base_due or intro_due or review_due or scene_due:
                reason = "scene" if scene_due and not (base_due or intro_due or review_due) else (
                    "review" if review_due else ("intro" if intro_due and not base_due else "base"))
                candidates.append(_candidate(idx, t, score, reason, hist, phash, gray))
            prev_hist = hist
            idx += 1
        stderr = p.communicate()[1].decode("utf-8", errors="replace")
        if p.returncode:
            raise RuntimeError(f"NVDEC 代理扫描失败({p.returncode}): {stderr[-240:]}")
        if idx == 0:
            raise RuntimeError(f"NVDEC 未输出视频帧: {stderr[-240:]}")
    except Exception:
        p.kill()
        p.communicate()
        raise
    return candidates


def _write_cpu(mp4, out_dir, candidates):
    wanted = {x["idx"]: i for i, x in enumerate(candidates, 1)}
    c = av.open(mp4)
    seen = 0
    try:
        for idx, frame in enumerate(c.decode(video=0)):
            order = wanted.get(idx)
            if order is not None:
                name = f"{order:04d}.jpg"
                frame.to_image().save(os.path.join(out_dir, name), "JPEG", quality=90)
                candidates[order - 1]["file"] = name
                seen += 1
    finally:
        c.close()
    if seen != len(candidates):
        raise RuntimeError(f"CPU 高清提取不完整: 需要 {len(candidates)} 帧，实际 {seen} 帧")


def _write_gpu(mp4, out_dir, candidates, meta):
    if not candidates:
        raise RuntimeError("没有可提取的候选帧")
    ffmpeg = probe.ffmpeg_path()
    expr = "+".join(f"eq(n\\,{x['idx']})" for x in candidates)
    width, height = max(2, meta["width"]), max(2, meta["height"])
    pattern = os.path.join(out_dir, "%04d.jpg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
           "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", mp4,
           "-an", "-vf", f"select='{expr}',scale_cuda={width}:{height},hwdownload,format=nv12",
           "-vsync", "0", "-frames:v", str(len(candidates)), "-q:v", "2", "-y", pattern]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        err = p.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"NVDEC 高清提取失败({p.returncode}): {err[-240:]}")
    files = sorted(glob.glob(os.path.join(out_dir, "*.jpg")))
    if len(files) != len(candidates):
        raise RuntimeError(f"GPU 高清提取不完整: 需要 {len(candidates)} 帧，实际 {len(files)} 帧")
    for i, item in enumerate(candidates, 1):
        item["file"] = f"{i:04d}.jpg"


def _clean_video_output(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.jpg")):
        try:
            os.remove(old)
        except OSError:
            pass
    meta_path = os.path.join(out_dir, "frames.json")
    if os.path.exists(meta_path):
        try:
            os.remove(meta_path)
        except OSError:
            pass


def extract(mp4, out_dir, fps, review_fps, scene_threshold, needs_review, min_frames,
            device="auto", max_frames=180, min_interval=0.20, review_intervals=None,
            review_source="none"):
    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "frames.json")
    source = {"mtime": os.path.getmtime(mp4), "size": os.path.getsize(mp4)}
    intervals = review_intervals or []
    config = {"schema_version": FRAME_SCHEMA_VERSION, "fps": fps, "review_fps": review_fps,
              "scene_threshold": scene_threshold, "min_frames": min_frames,
              "max_frames": max_frames, "min_interval": min_interval,
              "needs_visual_review": needs_review, "review_intervals": intervals,
              "review_source": review_source, "requested_device": device, "source": source}
    if os.path.exists(meta_path):
        try:
            old = json.load(open(meta_path, encoding="utf-8"))
            if old.get("completed") and old.get("config") == config and all(
                    os.path.exists(os.path.join(out_dir, r["file"])) for r in old.get("frames", [])):
                return len(old.get("frames", []))
        except Exception:
            pass
    _clean_video_output(out_dir)
    meta = _video_meta(mp4)
    requested = device
    fallback_reason = None
    scan_backend = "cpu"
    render_backend = "cpu"
    try:
        if device in ("auto", "cuda") and probe.cuda_decoder_available():
            raw_candidates = _run_gpu_proxy(mp4, meta, fps, review_fps, scene_threshold, intervals, min_frames)
            scan_backend = "cuda"
        else:
            if device == "cuda":
                fallback_reason = "cuda_decoder_unavailable"
            raw_candidates = _scan_cpu(mp4, meta, fps, review_fps, scene_threshold, intervals, min_frames)
    except Exception as e:
        if device == "cpu":
            raise
        fallback_reason = f"gpu_proxy: {str(e)[:180]}"
        print(f"  {mp4}: GPU 代理失败，回退 CPU（{str(e)[:100]}）", flush=True)
        raw_candidates = _scan_cpu(mp4, meta, fps, review_fps, scene_threshold, intervals, min_frames)
    candidates = _cap_candidates(_dedupe_candidates(raw_candidates, min_interval), max_frames)
    try:
        if scan_backend == "cuda" and device in ("auto", "cuda"):
            try:
                _write_gpu(mp4, out_dir, candidates, meta)
                render_backend = "cuda"
            except Exception as e:
                fallback_reason = (fallback_reason + "; " if fallback_reason else "") + f"gpu_render: {str(e)[:180]}"
                print(f"  {mp4}: GPU 高清提取失败，回退 CPU（{str(e)[:100]}）", flush=True)
                _clean_video_output(out_dir)
                _write_cpu(mp4, out_dir, candidates)
                render_backend = "cpu"
        else:
            _write_cpu(mp4, out_dir, candidates)
    except Exception:
        _clean_video_output(out_dir)
        raise
    records = []
    for item in candidates:
        records.append({k: item[k] for k in ("file", "timestamp", "reason", "scene_score",
                                               "brightness", "sharpness")})
    data = {"schema_version": FRAME_SCHEMA_VERSION, "adaptive": True, "completed": True,
            "source_type": "video", "requested_device": requested,
            "backend": render_backend, "scan_backend": scan_backend,
            "render_backend": render_backend, "fallback_reason": fallback_reason,
            "gpu_decoder": "nvdec" if scan_backend == "cuda" or render_backend == "cuda" else None,
            "gpu_scaler": "scale_cuda" if scan_backend == "cuda" or render_backend == "cuda" else None,
            "needs_visual_review": needs_review, "review_source": review_source,
            "config": config, "frames": records}
    temp = meta_path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, meta_path)
    return len(records)


def _worker(args):
    (mp4, outdir, fps, review_fps, threshold, review_map, min_frames,
     device, max_frames, min_interval) = args
    aid = os.path.splitext(os.path.basename(mp4))[0]
    info = review_map.get(aid, {})
    try:
        n = extract(mp4, os.path.join(outdir, aid), fps, review_fps, threshold,
                    bool(info.get("needs_visual_review")), min_frames, device,
                    max_frames, min_interval, info.get("intervals"), info.get("source", "none"))
        return aid, n, None
    except Exception as e:
        print(f"  {mp4}: ERR {str(e)[:180]}", flush=True)
        return aid, -1, str(e)


def import_note_images(image_root, frames_root):
    """Expose original note images through the same auditable frames contract."""
    total, notes = 0, 0
    for note_dir in sorted(glob.glob(os.path.join(image_root, "*"))):
        if not os.path.isdir(note_dir):
            continue
        aid = os.path.basename(note_dir)
        sources = sorted(glob.glob(os.path.join(note_dir, "*.jpg")))
        if not sources:
            continue
        out_dir = os.path.join(frames_root, aid)
        os.makedirs(out_dir, exist_ok=True)
        records = []
        for i, src in enumerate(sources, 1):
            name = f"{i:04d}.jpg"
            dst = os.path.join(out_dir, name)
            if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
            records.append({"file": name, "timestamp": None, "reason": "note_image",
                            "scene_score": None, "brightness": None, "sharpness": None})
        meta = {"adaptive": False, "completed": True, "source_type": "image_note",
                "config": {"source_files": [os.path.basename(x) for x in sources]}, "frames": records}
        with open(os.path.join(out_dir, "frames.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        notes += 1
        total += len(records)
    return notes, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True, help="账号 slug，如 myaccount")
    ap.add_argument("--fps", type=int, default=1, help="基础抽帧频率（帧/秒）")
    ap.add_argument("--review-fps", type=int, default=5, help="低置信度区间加密频率")
    ap.add_argument("--scene-threshold", type=float, default=0.18, help="镜头突变直方图阈值")
    ap.add_argument("--min-frames", type=int, default=12, help="每视频最低均匀覆盖采样点")
    ap.add_argument("--max-frames", type=int, default=180, help="每视频软上限（默认180）")
    ap.add_argument("--min-interval", type=float, default=0.20, help="候选帧最短间隔秒数")
    ap.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto",
                    help="抽帧后端：GPU优先/强制GPU尝试/CPU")
    ap.add_argument("--workers", type=int, default=None,
                    help="并行进程数（GPU缺省1，CPU缺省按内存与核数）")
    a = ap.parse_args()
    if a.fps <= 0 or a.review_fps <= 0 or a.min_frames <= 0 or a.max_frames <= 0 or a.min_interval < 0:
        sys.exit("[ERR] --fps/--review-fps/--min-frames/--max-frames 必须为正数，--min-interval 不得为负")

    cuda = probe.cuda_decoder_available()
    w = a.workers or probe.frame_workers(a.device)
    print(f"[资源] {probe.snapshot(probe.has_gpu())} | ffmpeg CUDA={'yes' if cuda else 'no'}"
          f" -> device={a.device}，抽帧进程数={w}", flush=True)

    vd = os.path.join(a.root, "videos", a.account)
    nd = os.path.join(a.root, "images", a.account)
    fd = os.path.join(a.root, "video-analysis", a.account, "frames")
    note_count, note_frames = import_note_images(nd, fd)
    if note_count:
        print(f"[图文] {note_count} 条原图，共 {note_frames} 帧", flush=True)
    review_map = {}
    for jp in glob.glob(os.path.join(a.root, "transcript", a.account, "*.json")):
        try:
            with open(jp, encoding="utf-8") as f:
                info = json.load(f)
            intervals, source = _review_intervals(info)
            review_map[os.path.splitext(os.path.basename(jp))[0]] = {
                "needs_visual_review": bool(info.get("needs_visual_review")),
                "intervals": intervals, "source": source}
        except Exception:
            pass
    tasks = [(mp4, fd, a.fps, a.review_fps, a.scene_threshold, review_map,
              a.min_frames, a.device, a.max_frames, a.min_interval)
             for mp4 in sorted(glob.glob(os.path.join(vd, "*.mp4")))]
    total, n0, failed = note_frames, len(tasks), []
    with Pool(w) as pool:
        for done, (aid, n, error) in enumerate(pool.imap_unordered(_worker, tasks), 1):
            if n < 0:
                failed.append(aid)
                print(f"  [{done}/{n0}] {aid}: ERR 解码失败 {error or ''}", flush=True)
            else:
                total += n
                print(f"  [{done}/{n0}] {aid}: {n} 帧", flush=True)
    print(f"\n[完成] {n0} 视频 + {note_count} 图文，共 {total} 帧（进程数 {w}）", flush=True)
    if failed:
        print(f"[ERR] {len(failed)} 个视频解码失败（无 frames.json，下游会整体跳过）：", flush=True)
        for aid in sorted(failed):
            print(f"      {aid}", flush=True)
        print("      处置：删除对应 videos/<account>/<aid>.mp4 后重跑 download.py，再重跑本工具", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
