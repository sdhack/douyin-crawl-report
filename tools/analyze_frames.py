# -*- coding: utf-8 -*-
"""Enrich adaptive frame timelines with OCR when local Tesseract is available."""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys


def ocr(image, tesseract):
    if not tesseract:
        return "", "unavailable"
    try:
        p = subprocess.run([tesseract, image, "stdout", "-l", "chi_sim+eng"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        return p.stdout.strip(), "ok" if p.returncode == 0 else "failed"
    except Exception:
        return "", "failed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    a = ap.parse_args()
    base = os.path.join(a.root, "video-analysis", a.account, "frames")
    tesseract = shutil.which("tesseract")
    timelines = glob.glob(os.path.join(base, "*", "frames.json"))
    if not timelines:
        sys.exit(f"[ERR] 未找到逐帧时间轴: {base}")
    for i, path in enumerate(timelines, 1):
        data = json.load(open(path, encoding="utf-8"))
        for row in data.get("frames", []):
            text, status = ocr(os.path.join(os.path.dirname(path), row["file"]), tesseract)
            row["ocr_text"] = text
            row["ocr_status"] = status
        data["ocr_engine"] = tesseract or None
        data["ocr_available"] = bool(tesseract)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[{i}/{len(timelines)}] {os.path.basename(os.path.dirname(path))}: {len(data.get('frames', []))} 帧")
    print(f"[完成] 画面时间轴={len(timelines)} OCR={'启用' if tesseract else '不可用（已明确标记）'}")


if __name__ == "__main__":
    main()
