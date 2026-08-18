# -*- coding: utf-8 -*-
"""组装"每视频全维度档案"，供单视频逆向拆解 + 全量标准化标签 + 账号总结取数。

将 manifest + 口播转写 + BGM 归档 + 帧(1fps) + 评论聚合 合成每视频一份紧凑档案：
  <root>/decompose/<account>/video_profiles.json  (机器可读，供脚本/打标)
  <root>/decompose/<account>/video_profiles.md   (紧凑可读，供 LLM 快速浏览)

用法: python tools/decompose_prep.py --root <根> --account <slug>
输入依赖: video-analysis/<acct>/manifest.json、transcript/<acct>/*.json、
          bgm/<acct>/*.json、video-analysis/<acct>/frames/<aid>/、comments.json(可选，缺则评论维度标缺源)
"""
import argparse, glob, json, os, datetime, math


def fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def key_frames(fdir):
    """从 1fps 帧目录挑代表帧：首段 hook(前5帧)+1/3+2/3+尾。返回相对 fdir 的文件名列表。"""
    fs = sorted(f for f in os.listdir(fdir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
    if not fs:
        return []
    n = len(fs)
    idx = sorted(set([0, 1, 2, 3, 4] + [int(n * i / 3) for i in range(1, 3)] + [n - 1]))
    return [fs[i] for i in idx if i < n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    a = ap.parse_args()

    root, acct = a.root, a.account
    mf = os.path.join(root, "video-analysis", acct, "manifest.json")
    manifest = json.load(open(mf, encoding="utf-8"))

    trans = {}
    for f in glob.glob(os.path.join(root, "transcript", acct, "*.json")):
        try:
            t = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        trans[str(t.get("aweme_id"))] = t

    bgm = {}
    for f in glob.glob(os.path.join(root, "bgm", acct, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            b = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        bgm[str(b.get("aweme_id"))] = b

    comp = {}
    cpath = os.path.join(root, "video-analysis", acct, "comments.json")
    comments = json.load(open(cpath, encoding="utf-8")).get("by_aweme", {}) if os.path.isfile(cpath) else {}

    covered = 0
    for r in manifest:
        aid = str(r["aweme_id"])
        t = trans.get(aid, {})
        b = bgm.get(aid, {})
        segs = t.get("segments") or []
        full = "".join((s.get("text") or "").strip() for s in segs) or t.get("text") or ""
        fdir = os.path.join(root, "video-analysis", acct, "frames", aid)
        kf = key_frames(fdir) if os.path.isdir(fdir) else []
        cm = comments.get(aid)
        has_com = bool(cm and isinstance(cm, dict) and cm.get("comments"))
        if has_com:
            covered += 1
        comp[aid] = {
            "rank": r.get("rank"),
            "aweme_id": aid,
            "title": r.get("title", ""),
            "create_time": fmt_ts(r.get("create_time")),
            "likes": r.get("likes", 0),
            "comment_count": r.get("comments", 0),  # 该视频的评论总数（互动指标）
            "collects": r.get("collects", 0),
            "shares": r.get("shares", 0),
            "duration_sec": round(t.get("duration") or b.get("duration_sec") or (len(os.listdir(fdir)) if os.path.isdir(fdir) else 0), 1),
            "transcript": full,
            "bgm_level": b.get("bgm_level", "?"),
            "mood": b.get("mood", "?"),
            "vocal": b.get("vocal", "?"),
            "bgm_text": b.get("bgm_text", ""),
            "frames_dir": fdir.replace("\\", "/").split(root.replace("\\", "/"))[-1].lstrip("/"),
            "frame_count": len(os.listdir(fdir)) if os.path.isdir(fdir) else 0,
            "key_frames": kf,
            "comments": (cm.get("comments") if has_com else None),  # 抓到的评论数组（无则 None）
            "comment_n": (cm.get("n") if has_com else 0),
        }

    od = os.path.join(root, "decompose", acct)
    os.makedirs(od, exist_ok=True)
    jp = os.path.join(od, "video_profiles.json")
    json.dump(comp, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 紧凑 md
    order = sorted(comp.values(), key=lambda v: v.get("rank") or 9999)
    lines = [f"# {acct} 视频档案（{len(order)} 条，评论覆盖 {covered}）", ""]
    for v in order:
        lines.append(f"## [{v['rank']}] {v['aweme_id']}｜{v['create_time']}｜{v['likes']}赞/{v['collects']}藏/{v['shares']}享/评论{v['comment_count']}(抓{v['comment_n']})｜{v['duration_sec']}s｜BGM:{v['bgm_level']}/{v['mood']}")
        lines.append(f"- 标题：{v['title']}")
        lines.append(f"- 口播：{v['transcript'][:200] or '(无口播)'}")
        if v["comment_n"]:
            top3 = " / ".join((c["content"][:30]) for c in v["comments"][:3])
            lines.append(f"- 高赞评论：{top3}")
        lines.append("")
    md = "\n".join(lines)
    open(os.path.join(od, "video_profiles.md"), "w", encoding="utf-8").write(md)

    n_frames = sum(1 for v in order if v["frame_count"])
    print(f"[decompose_prep] {acct}：{len(order)} 条 | 转写 {len(trans)} | BGM {len(bgm)} | 评论覆盖 {covered} | 帧目录 {n_frames}")
    print(f"[output] {jp}")

if __name__ == "__main__":
    main()