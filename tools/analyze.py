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
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_progress import RunProgress  # noqa: E402


def run_tool(name, args):
    cmd = [sys.executable, os.path.join(HERE, name)] + args
    print("[run] " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=os.getcwd()).returncode


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
    ap.add_argument("--map", default=None)
    ap.add_argument("--bgm-workers", type=int, default=None)
    ap.add_argument("--skip-bgm", action="store_true")
    a = ap.parse_args()
    progress = RunProgress(a.root, "analysis").heartbeat()

    common = ["--root", a.root, "--account", a.account]
    frame = common + ["--fps", str(a.fps)]
    if a.frame_workers is not None:
        frame += ["--workers", str(a.frame_workers)]
    transcribe = common + ["--model", a.model, "--device", a.device, "--compute", a.compute]
    if a.transcribe_workers is not None:
        transcribe += ["--workers", str(a.transcribe_workers)]
    if a.map:
        transcribe += ["--map", a.map]

    print("[阶段 1/3] 口播音频转写（生成低置信度核验标记）", flush=True)
    progress.detail("阶段 1/3：口播音频转写")
    code = run_tool("transcribe.py", transcribe)
    if code != 0:
        print(f"[停止] 口播转写失败，退出码={code}。", file=sys.stderr)
        progress.finish(False, f"口播转写失败：{code}")
        return 1

    print("[阶段 2/3] 自适应抽帧与 BGM 并行", flush=True)
    progress.detail("阶段 2/3：自适应抽帧与 BGM")
    bgm = common
    if a.bgm_workers is not None:
        bgm += ["--workers", str(a.bgm_workers)]
    jobs = [("extract_frames.py", frame)]
    if not a.skip_bgm:
        jobs.append(("transcribe_bgm.py", bgm))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        codes = [f.result() for f in [ex.submit(run_tool, name, args) for name, args in jobs]]
    if any(c != 0 for c in codes):
        print(f"[停止] 抽帧/BGM 失败，退出码={codes}。", file=sys.stderr)
        progress.finish(False, f"抽帧/BGM 失败：{codes}")
        return 1
    print("[阶段 3/3] 逐帧画面指标与字幕 OCR", flush=True)
    progress.detail("阶段 3/3：逐帧画面指标与字幕 OCR")
    code = run_tool("analyze_frames.py", common)
    if code != 0:
        progress.finish(False, f"画面分析失败：{code}")
        return code
    progress.finish(True, "内容分析完成")
    print("[完成] 口播转写 + 自适应逐帧画面分析 + BGM", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
