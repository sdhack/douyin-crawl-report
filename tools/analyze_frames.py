# -*- coding: utf-8 -*-
"""Auditable frame/video visual-style analysis with explicit uncertainty."""
import argparse, collections, glob, json, os, shutil, subprocess, sys
from multiprocessing import Pool
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402


def rnd(v): return round(float(v), 3)


def ocr(path, exe):
    if not exe: return "", [], "unavailable"
    try:
        p = subprocess.run([exe, path, "stdout", "-l", "chi_sim+eng", "tsv"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        if p.returncode: return "", [], "failed"
        boxes = []
        for line in p.stdout.splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 12 and c[11].strip():
                try: conf, box = float(c[10]), [int(c[i]) for i in range(6, 10)]
                except ValueError: continue
                if conf >= 20: boxes.append({"text": c[11].strip(), "confidence": rnd(conf / 100), "box": box})
        return " ".join(x["text"] for x in boxes), boxes, "ok"
    except Exception: return "", [], "failed"


def imread_unicode(path):
    # cv2.imread 在 Windows 下打不开含中文/非 ASCII 的路径（静默返回 None，
    # 曾导致 frames_analyzed: 0），改用 np.fromfile + cv2.imdecode 读字节流。
    try:
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def analyze(path, exe):
    bgr = imread_unicode(path)
    if bgr is None: raise RuntimeError("image decode failed")
    h, w = bgr.shape[:2]; hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV); gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hue, sat, val = [rnd(np.mean(hsv[:, :, i])) for i in range(3)]
    edges = cv2.Canny(gray, 80, 160); gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    weight = cv2.magnitude(gx, gy) + 1e-6; yy, xx = np.indices(gray.shape)
    cx, cy = rnd(np.sum(xx * weight) / np.sum(weight) / w), rnd(np.sum(yy * weight) / np.sum(weight) / h)
    comp = "centered" if abs(cx-.5)<.12 and abs(cy-.5)<.12 else ("rule_of_thirds" if min(abs(cx-1/3),abs(cx-2/3),abs(cy-1/3),abs(cy-2/3))<.10 else "asymmetric")
    rgb = bgr.mean(axis=(0, 1))[::-1]; temp = "warm" if rgb[0]>rgb[2]*1.08 else ("cool" if rgb[2]>rgb[0]*1.08 else "neutral")
    style = ("high_key" if val>175 and np.std(gray)<65 else ("low_key" if val<90 else "balanced")) + ("_vivid" if sat>125 else ("_muted" if sat<55 else ""))
    upper = hsv[:max(1, h//3)]; blue = np.mean((upper[:,:,0]>=85)&(upper[:,:,0]<=130)&(upper[:,:,1]>45))
    scene = "outdoor_candidate" if blue>.16 and val>105 else "indoor_or_closeup_candidate"
    text, boxes, status = ocr(path, exe); region = "unknown"
    if boxes:
        my = np.mean([(b["box"][1]+b["box"][3]/2)/h for b in boxes]); region = "top" if my<.35 else ("bottom" if my>.65 else "middle")
    center = edges[h//4:3*h//4,w//4:3*w//4]; sal = rnd(np.mean(center>0)) if center.size else 0
    candidate = bool(sal>.12 or any(k in text.lower() for k in ("¥","元","ml","kg")))
    return {"color":{"mean_hsv":[hue,sat,val],"temperature":temp,"contrast":rnd(np.std(gray))},
            "visual_style":style,"edge_density":rnd(np.mean(edges>0)),
            "composition":{"type":comp,"visual_center":[cx,cy]},
            "scene":{"label":scene,"confidence":rnd(min(.75,.35+blue)),"status":"heuristic_requires_review"},
            "ocr_text":text,"ocr_boxes":boxes,"ocr_status":status,
            "subtitle_style":{"present":bool(boxes),"region":region,"coverage":rnd(sum(b["box"][2]*b["box"][3] for b in boxes)/(w*h))},
            "product_exposure":{"candidate":candidate,"center_saliency":sal,"confidence":"low","status":"requires_object_detection_or_review"}}


def summary(frames):
    good=[r for r in frames if "analysis" in r]; mode=lambda xs: collections.Counter(xs).most_common(1)[0][0] if xs else "unknown"
    subs=[r for r in good if r["analysis"]["subtitle_style"]["present"]]; prod=[r for r in good if r["analysis"]["product_exposure"]["candidate"]]
    return {"frames_analyzed":len(good),"visual_style":mode([r["analysis"]["visual_style"] for r in good]),
            "color":{"temperature":mode([r["analysis"]["color"]["temperature"] for r in good]),
                     "mean_hsv":[rnd(np.mean([r["analysis"]["color"]["mean_hsv"][i] for r in good])) for i in range(3)] if good else []},
            "composition":{"dominant":mode([r["analysis"]["composition"]["type"] for r in good])},
            "scene":{"dominant_candidate":mode([r["analysis"]["scene"]["label"] for r in good]),"status":"heuristic_requires_review"},
            "subtitles":{"frame_ratio":rnd(len(subs)/len(good)) if good else 0,"dominant_region":mode([r["analysis"]["subtitle_style"]["region"] for r in subs])},
            "product_exposure":{"candidate_frame_ratio":rnd(len(prod)/len(good)) if good else 0,"candidate_timestamps":[r.get("timestamp") for r in prod],"status":"candidates_require_review"},
            "limitations":["scene is heuristic","product exposure is candidate detection, not product recognition"]}


def _work(job):
    path, exe = job
    try:
        return analyze(path, exe), None
    except Exception as e:
        return None, str(e)


def analyze_workers():
    """逐帧分析是 CPU-bound（cv2 指标 + 每帧一个 tesseract 子进程）。
    单进程实测约 2s/帧（tesseract 每次冷启动加载 chi_sim+eng），14 视频约 2 小时；
    帧间无共享状态，进程池并行。每 worker 峰值内存远低于抽帧（约 0.5GB），封顶 8。"""
    cores = probe.cpus()
    m = probe.mem()
    mem_cap = max(1, int(m["avail_gb"] / 0.5)) if m["avail_gb"] > 0.5 else 1
    return max(1, min(cores, 8, mem_cap))


def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",required=True); p.add_argument("--account",required=True)
    p.add_argument("--workers",type=int,default=None); a=p.parse_args()
    base=os.path.join(a.root,"video-analysis",a.account,"frames"); paths=glob.glob(os.path.join(base,"*","frames.json")); exe=shutil.which("tesseract")
    if not paths: sys.exit(f"[ERR] 未找到逐帧时间轴: {base}")
    w=a.workers or analyze_workers()
    print(f"[资源] {probe.snapshot(probe.has_gpu())} -> 画面分析进程数={w}", flush=True)
    videos=[]
    with Pool(w) as pool:
        for i,path in enumerate(paths,1):
            data=json.load(open(path,encoding="utf-8"))
            rows=data.get("frames",[])
            dirpath=os.path.dirname(path)
            # 断点续帧：已有 analysis 的帧直接复用，中断重跑只补增量
            todo=[(idx,os.path.join(dirpath,r["file"])) for idx,r in enumerate(rows) if "analysis" not in r]
            if todo:
                results=pool.map(_work,[(fp,exe) for _,fp in todo])
                for (idx,_),(res,err) in zip(todo,results):
                    if err is not None: rows[idx]["analysis_error"]=err
                    else: rows[idx]["analysis"]=res
            data["ocr_engine"]=exe; data["ocr_available"]=bool(exe); out=summary(rows); out["aweme_id"]=os.path.basename(dirpath)
            with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
            with open(os.path.join(dirpath,"visual-summary.json"),"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
            videos.append(out); print(f"[{i}/{len(paths)}] {out['aweme_id']}: {out['frames_analyzed']} 帧", flush=True)
    with open(os.path.join(a.root,"video-analysis",a.account,"_visual-summary.json"),"w",encoding="utf-8") as f: json.dump({"account":a.account,"videos":videos},f,ensure_ascii=False,indent=2)
    print(f"[完成] 视觉分析={len(videos)} OCR={'启用' if exe else '不可用（已明确标记）'}", flush=True)


if __name__=="__main__": main()
