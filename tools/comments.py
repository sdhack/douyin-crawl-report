# -*- coding: utf-8 -*-
"""评论提取与聚合：把 {mode}_comments_*.jsonl 按视频聚合成结构化数据。

供"评论区分析"维度取数。MediaCrawler 评论文件名前缀随抓取模式变化：
detail 模式产 detail_comments_*.jsonl，creator 批量产 creator_comments_*.jsonl，
故按 *_comments_*.jsonl 全量匹配（跨天续跑多文件一并合并）。输出:
  <root>/video-analysis/<account>/comments.json
    { aweme_id: { n, max:截断上限, comments: [ {content, nickname, like_count, create_time}, ... ] } }
    summary: { total_videos, total_comments, covered_aweme_ids }
截断策略: 每视频按 like_count 降序取前 --max 条(默认 100)，保留代表性评论。
用法: python tools/comments.py --root <根> --account <slug> [--max 100]
来源: <root>/crawl_<account>/**/*_comments_*.jsonl，或显式 --comments-path
"""
import argparse, glob, json, os, datetime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--max", type=int, default=100, help="每视频保留评论条数上限(按赞降序，默认100)")
    ap.add_argument("--comments-path", default=None, help="comments jsonl 直接指定(可选)")
    a = ap.parse_args()

    fps = []
    if a.comments_path and os.path.isfile(a.comments_path):
        fps = [a.comments_path]
    else:
        pat = os.path.join(a.root, "crawl_" + a.account, "**", "*_comments_*.jsonl")
        fps = sorted(glob.glob(pat, recursive=True))

    manifest_path = os.path.join(a.root, "video-analysis", a.account, "manifest.json")
    allowed_aweme_ids = None
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            allowed_aweme_ids = {str(x.get("aweme_id")) for x in json.load(f) if x.get("aweme_id")}

    by_aweme = {}
    total = 0
    corrupt = 0   # 并发写竞态会留残行（实测丢记录头/尾），跳过数必须显式曝光而非静默
    seen = {}   # aid -> set(去重键)，重跑会重复追加：有 comment_id 用 id，无则用 (内容,昵称) 兜底
    for f in fps:
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ct = json.loads(line)
            except Exception:
                corrupt += 1
                continue
            aid = str(ct.get("aweme_id") or "")
            content = (ct.get("content") or "").strip()
            cid = str(ct.get("comment_id") or "")
            if not aid or not content:
                continue
            if allowed_aweme_ids is not None and aid not in allowed_aweme_ids:
                continue
            key = ("id", cid) if cid else ("txt", content, ct.get("nickname") or "")
            s = seen.setdefault(aid, set())
            if key in s:
                continue
            s.add(key)
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
    # 原子写：半截 comments.json 会让 decompose_prep 崩溃、report_html 误报缺源
    tmp = op + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "source_files": [os.path.basename(f) for f in fps],
                "total_comments": total,
                "corrupt_lines_skipped": corrupt,
                "total_videos_with_comments": len(covered),
                "covered_aweme_ids": covered,
            },
            "by_aweme": out,
        }, f, ensure_ascii=False, indent=1)
    os.replace(tmp, op)
    print(f"[comments] 源文件 {len(fps)} 个 | 原始评论 {total} 条 | 覆盖视频 {len(covered)} 个")
    if corrupt:
        print(f"[comments][警告] 跳过 {corrupt} 行损坏 JSON（并发写竞态痕迹，建议并发=1 重抓评论或已修复的 MediaCrawler）")
    print(f"[comments] 每视频按赞降序截断 top {a.max}，输出 {op}")

if __name__ == "__main__":
    main()
