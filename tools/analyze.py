# -*- coding: utf-8 -*-
"""并行内容分析编排器：抽帧 + 口播转写并行，完成后执行 BGM。

前提：已完成 process.py 和 download.py。
用法:
  python tools/analyze.py --root <root> --account <slug>
可选：--fps 1 --frame-workers 4 --transcribe-workers 2 --bgm-workers 2

设计约束：抽帧与口播转写可并行；BGM 默认串行执行，避免与口播转写争抢 GPU。
任一阶段失败立即返回非零退出码，不生成或使用兜底结果。
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


HERE = os.path.dirname(os.path.abspath(__file__))


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

    common = ["--root", a.root, "--account", a.account]
    frame = common + ["--fps", str(a.fps)]
    if a.frame_workers is not None:
        frame += ["--workers", str(a.frame_workers)]
    transcribe = common + ["--model", a.model, "--device", a.device, "--compute", a.compute]
    if a.transcribe_workers is not None:
        transcribe += ["--workers", str(a.transcribe_workers)]
    if a.map:
        transcribe += ["--map", a.map]

    print("[阶段 1/2] 抽帧与口播转写并行执行", flush=True)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(run_tool, "extract_frames.py", frame),
                   ex.submit(run_tool, "transcribe.py", transcribe)]
        codes = [f.result() for f in futures]
    if any(c != 0 for c in codes):
        print(f"[停止] 抽帧/口播转写失败，退出码={codes}；不执行 BGM 或其他兜底。", file=sys.stderr)
        return 1

    if a.skip_bgm:
        print("[完成] 抽帧 + 口播转写；按 --skip-bgm 跳过 BGM。", flush=True)
        return 0

    print("[阶段 2/2] 口播完成，开始 BGM（串行避免 GPU 争抢）", flush=True)
    bgm = common
    if a.bgm_workers is not None:
        bgm += ["--workers", str(a.bgm_workers)]
    code = run_tool("transcribe_bgm.py", bgm)
    if code != 0:
        print(f"[停止] BGM 分析失败，退出码={code}；不执行其他兜底。", file=sys.stderr)
        return code or 1
    print("[完成] 抽帧 + 口播转写 + BGM", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
