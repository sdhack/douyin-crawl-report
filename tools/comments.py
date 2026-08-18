# -*- coding: utf-8 -*-
"""评论提取与聚合：把 detail_comments_*.jsonl 按视频聚合成结构化数据。

供"评论区分析"维度取数。输出:
  <root>/video-analysis/<account>/comments.json
    { aweme_id: { n, max:截断上限, comments: [ {content, nickname, like_count, create_time}, ... ] } }
    summary: { total_videos, total_comments, covered_aweme_ids }
截断策略: 每视频按 like_count 降序取前 --max 条(默认 100)，保留代表性评论。
用法: python tools/comments.py --root <根> --account <slug> [--max 100]
来源: <root>/crawl_comments/**/detail_comments_*.jsonl  或  <root>/data/douyin/**/detail_comments_*.jsonl
"""
import argparse, glob, json, os, datetime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--max", type=int, default=100, help="每视频保留评论条数上限(按赞降序，默认100)")
    ap.add_argument("--comments-path", default=None, help="detail_comments jsonl 直接指定(可选)")
    a = ap.parse_args()

    fps = []
    if a.comments_path and os.path.isfile(a.comments_path):
        fps = [a.comments_path]
    else:
        for base in ("crawl_comments", "data"):
            pat = os.path.join(a.root, base, "**", "detail_comments*.jsonl")
            fps += sorted(glob.glob(pat, recursive=True))

    by_aweme = {}
    total = 0
    seen = {}   # aid -> set(comment_id)，重跑会重复追加，按 comment_id 去重
    for f in fps:
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ct = json.loads(line)
            except Exception:
                continue
            aid = str(ct.get("aweme_id") or "")
            content = (ct.get("content") or "").strip()
            cid = str(ct.get("comment_id") or "")
            if not aid or not content:
                continue
            if cid:
                s = seen.setdefault(aid, set())
                if cid in s:
                    continue
                s.add(cid)
            total += 1
            by_aweme.setdefault(aid, []).append({
                "content": content,
                "nickname": ct.get("nickname") or "",
                "like_count": int(ct.get("like_count") or 0),
                "create_time": ct.get("create_time"),
                "comment_id": cid,
            })

    out = {}
    covered = sorted(by_aweme.keys())
    for aid, items in by_aweme.items():
        items.sort(key=lambda c: c["like_count"], reverse=True)
        cut = items[: a.max]
        out[aid] = {"n": len(cut), "max": a.max, "comments": cut}

    op = os.path.join(a.root, "video-analysis", a.account, "comments.json")
    os.makedirs(os.path.dirname(op), exist_ok=True)
    json.dump({
        "summary": {
            "source_files": [os.path.basename(f) for f in fps],
            "total_comments": total,
            "total_videos_with_comments": len(covered),
            "covered_aweme_ids": covered,
        },
        "by_aweme": out,
    }, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[comments] 源文件 {len(fps)} 个 | 原始评论 {total} 条 | 覆盖视频 {len(covered)} 个")
    print(f"[comments] 每视频按赞降序截断 top {a.max}，输出 {op}")

if __name__ == "__main__":
    main()