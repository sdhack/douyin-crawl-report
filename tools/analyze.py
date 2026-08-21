# -*- coding: utf-8 -*-
"""内容分析编排器：音频转写后，自适应抽帧与 BGM 并行，再做画面分析。

前提：已完成 process.py 和 download.py。
用法:
  python tools/analyze.py --root <root> --account <slug>
可选：--fps 1 --frame-workers 4 --transcribe-workers 2 --bgm-workers 2

设计约束：口播转写先行；随后抽帧与 BGM 并行，两者均不与口播转写同时运行，避免争抢 GPU。
任一阶段失败立即返回非零退出码，不生成或使用兜底结果。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_progress import RunProgress  # noqa: E402


def run_tool(name, args, on_line=None):
    cmd = [sys.executable, os.path.join(HERE, name)] + args
    print("[run] " + " ".join(cmd), flush=True)
    if on_line is None:
        return subprocess.run(cmd, cwd=os.getcwd()).returncode
    proc = subprocess.Popen(cmd, cwd=os.getcwd(), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1)
    for raw in proc.stdout:
        line = raw.rstrip()
        print(line, flush=True)
        on_line(line)
    return proc.wait()


def _json_records(path):
    count = 0
    if not os.path.isdir(path):
        return 0
    for name in os.listdir(path):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(path, name), encoding="utf-8") as f:
                if isinstance(json.load(f), dict):
                    count += 1
        except (OSError, ValueError):
            pass
    return count


def _artifact_metrics(root, account, stage):
    """从子工具产物读取可复核的 artifacts_total/backend，不依赖日志文案。"""
    base = os.path.join(root, "video-analysis", account)
    if stage == "transcribe":
        total = _json_records(os.path.join(root, "transcript", account))
        return {"artifacts_total": total, "items": total}
    if stage == "extract_frames":
        frames_root = os.path.join(base, "frames")
        videos, frames, backends = 0, 0, []
        if os.path.isdir(frames_root):
            for aid in os.listdir(frames_root):
                meta_path = os.path.join(frames_root, aid, "frames.json")
                if not os.path.isfile(meta_path):
                    continue
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("completed"):
                        videos += 1
                    frames += len(data.get("frames") or [])
                    for key in ("backend", "render_backend", "scan_backend"):
                        if data.get(key):
                            backends.append(str(data[key]))
                            break
                except (OSError, ValueError):
                    pass
        return {"artifacts_total": videos, "items": videos, "frames": frames,
                "backend_values": backends}
    if stage in ("bgm", "transcribe_bgm"):
        path = os.path.join(root, "bgm", account, "_manifest.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            total = int(data.get("n") or 0)
            return {"artifacts_total": total, "items": total}
        except (OSError, ValueError, TypeError):
            return {"artifacts_total": 0, "items": 0}
    if stage in ("visual", "analyze_frames"):
        try:
            with open(os.path.join(base, "_visual-summary.json"), encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("videos") if isinstance(data, dict) else []
            total = len(rows or [])
            return {"artifacts_total": total, "items": total, "backend": "cpu"}
        except (OSError, ValueError, TypeError):
            return {"artifacts_total": 0, "items": 0, "backend": "cpu"}
    return {"artifacts_total": 0, "items": 0}


def _backend_from_lines(lines, fallback):
    for line in lines:
        match = re.search(r"实际生效 device=([^/\s]+)", line)
        if match:
            return match.group(1)
    for line in lines:
        match = re.search(r"(?:->\s*)?device=(cuda|cpu)\b", line)
        if match:
            return match.group(1)
    return fallback


def run_stage(name, args, root, account, fallback_backend, progress=None, label=""):
    lines = []
    started = time.perf_counter()

    def observe(line):
        lines.append(line)
        if progress is not None:
            progress.observe("%s: %s" % (label or name, line[-180:]))

    try:
        code = run_tool(name + ".py" if not name.endswith(".py") else name, args, on_line=observe)
    except Exception as exc:
        lines.append("runner error: %s" % exc)
        print("[run-error] %s: %s" % (name, exc), file=sys.stderr, flush=True)
        code = 1
    elapsed = max(0.0, time.perf_counter() - started)
    found = _artifact_metrics(root, account, name.replace(".py", ""))
    backend_values = found.pop("backend_values", [])
    backend = (Counter(backend_values).most_common(1)[0][0] if backend_values else
               found.pop("backend", None) or _backend_from_lines(lines, fallback_backend))
    # artifacts_total/items are completed artifacts available after this stage;
    # throughput is artifacts_total divided by the full stage duration, not newly-created work.
    artifacts_total = int(found.pop("artifacts_total", found.pop("items", 0)) or 0)
    found.pop("items", None)
    metrics = {"duration_sec": round(elapsed, 3), "backend": backend,
               "artifacts_total": artifacts_total, "items": artifacts_total,
               "throughput": round(artifacts_total / elapsed, 3) if elapsed else 0.0,
               "returncode": code, "status": "completed" if code == 0 else "failed"}
    metrics.update(found)
    return code, metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--fps", type=int, default=1)
    ap.add_argument("--frame-workers", type=int, default=None)
    ap.add_argument("--transcribe-workers", type=int, default=None)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute", default="auto")
    ap.add_argument("--frame-device", choices=("auto", "cuda", "cpu"), default=None,
                    help="抽帧后端，透传给 extract_frames.py --device")
    ap.add_argument("--hwaccel", choices=("auto", "cuda", "cpu"), default=None,
                    help="抽帧硬件加速别名；extract_frames.py 当前以 --device 接收该值")
    ap.add_argument("--map", default=None)
    ap.add_argument("--bgm-workers", type=int, default=None)
    ap.add_argument("--skip-bgm", action="store_true")
    a = ap.parse_args()
    if a.frame_device and a.hwaccel and a.frame_device != a.hwaccel:
        ap.error("--frame-device 与 --hwaccel 不能指定不同后端")
    frame_device = a.frame_device or a.hwaccel or "auto"
    progress = RunProgress(a.root, "analysis").heartbeat()
    pipeline_started = time.perf_counter()
    stages = {}

    common = ["--root", a.root, "--account", a.account]
    # extract_frames.py 的真实 CLI 是 --device；该参数内部选择 NVDEC/scale_cuda，
    # 不伪造一个不存在的 --hwaccel 选项，--hwaccel 仅作为上面的兼容别名。
    frame = common + ["--fps", str(a.fps), "--device", frame_device]
    if a.frame_workers is not None:
        frame += ["--workers", str(a.frame_workers)]
    transcribe = common + ["--model", a.model, "--device", a.device, "--compute", a.compute]
    if a.transcribe_workers is not None:
        transcribe += ["--workers", str(a.transcribe_workers)]
    if a.map:
        transcribe += ["--map", a.map]

    print("[阶段 1/3] 口播音频转写（生成低置信度核验标记）", flush=True)
    progress.detail("阶段 1/3：口播音频转写", stages={"transcribe": {"backend": a.device, "items": 0}})
    code, transcribe_metrics = run_stage("transcribe", transcribe, a.root, a.account,
                                         a.device, progress, "口播转写")
    stages["transcribe"] = transcribe_metrics
    progress.detail("阶段 1/3完成：口播音频转写", stages=stages)
    if code != 0:
        print(f"[停止] 口播转写失败，退出码={code}。", file=sys.stderr)
        progress.finish(False, f"口播转写失败：{code}", stages=stages,
                        pipeline_duration_sec=round(time.perf_counter() - pipeline_started, 3))
        return 1

    print("[阶段 2/3] 自适应抽帧与 BGM 并行", flush=True)
    progress.detail("阶段 2/3：自适应抽帧与 BGM", stages=stages)
    bgm = common
    if a.bgm_workers is not None:
        bgm += ["--workers", str(a.bgm_workers)]
    jobs = [("extract_frames", frame, frame_device, "自适应抽帧")]
    if not a.skip_bgm:
        jobs.append(("transcribe_bgm", bgm, "cpu", "BGM分析"))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = {name: ex.submit(run_stage, name, args, a.root, a.account, backend,
                                   progress, label)
                   for name, args, backend, label in jobs}
        stage_results = {name: future.result() for name, future in futures.items()}
    for name, (stage_code, stage_metrics) in stage_results.items():
        stages[name] = stage_metrics
    if a.skip_bgm:
        stages["transcribe_bgm"] = {"duration_sec": 0.0, "backend": "skipped",
                                     "artifacts_total": 0, "items": 0, "throughput": 0.0,
                                     "returncode": 0, "status": "skipped"}
    progress.detail("阶段 2/3完成：自适应抽帧与 BGM", stages=stages)
    codes = [result[0] for result in stage_results.values()]
    if any(c != 0 for c in codes):
        print(f"[停止] 抽帧/BGM 失败，退出码={codes}。", file=sys.stderr)
        progress.finish(False, f"抽帧/BGM 失败：{codes}", stages=stages,
                        pipeline_duration_sec=round(time.perf_counter() - pipeline_started, 3))
        return 1
    print("[阶段 3/3] 逐帧画面指标与字幕 OCR", flush=True)
    progress.detail("阶段 3/3：逐帧画面指标与字幕 OCR", stages=stages)
    code, visual_metrics = run_stage("analyze_frames", common, a.root, a.account,
                                     "cpu", progress, "逐帧画面分析")
    stages["analyze_frames"] = visual_metrics
    progress.detail("阶段 3/3完成：逐帧画面指标与字幕 OCR", stages=stages)
    if code != 0:
        progress.finish(False, f"画面分析失败：{code}", stages=stages,
                        pipeline_duration_sec=round(time.perf_counter() - pipeline_started, 3))
        return code
    progress.finish(True, "内容分析完成", stages=stages,
                    pipeline_duration_sec=round(time.perf_counter() - pipeline_started, 3))
    print("[完成] 口播转写 + 自适应逐帧画面分析 + BGM", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
