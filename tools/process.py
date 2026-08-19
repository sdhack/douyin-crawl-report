# -*- coding: utf-8 -*-
"""数据处理：jsonl 按 aweme_id 去重 -> 排序 -> 生成 manifest.json（下载清单）
用法: python tools/process.py --root <工作根> --account <slug> [--json <去重jsonl>]
  --json 缺省时只取当前运行目录 <root>/crawl_<account>/douyin/jsonl/*.jsonl 中最新一个。
输出: <root>/video-analysis/<account>/manifest.json
"""
import argparse, json, os, sys, glob


def latest_jsonl(root, account):
    # Never scan another account's crawl directory. Legacy shared layouts must
    # be supplied explicitly with --json because their ownership is ambiguous.
    pattern = os.path.join(root, "crawl_" + account, "douyin", "jsonl", "*.jsonl")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="工作根目录（产物落在此目录）")
    ap.add_argument("--account", required=True, help="仅用于目录命名的 slug，如 myaccount")
    ap.add_argument("--json", default=None, help="去重前原始 jsonl 路径")
    a = ap.parse_args()

    src = a.json or latest_jsonl(a.root, a.account)
    if not src or not os.path.exists(src):
        sys.exit(f"[ERR] 找不到当前账号 jsonl: {src or f'crawl_{a.account}/douyin/jsonl 为空'}。旧共享目录必须显式传 --json。")

    outdir = os.path.join(a.root, "video-analysis", a.account)
    os.makedirs(outdir, exist_ok=True)

    records, seen = [], set()
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            aid = j.get("aweme_id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            records.append(j)

    for r in records:
        r["_likes"] = int(r.get("liked_count") or 0)
        r["_comments"] = int(r.get("comment_count") or 0)
        r["_collects"] = int(r.get("collected_count") or 0)
        r["_shares"] = int(r.get("share_count") or 0)
        r["_score"] = r["_likes"] * 1 + r["_comments"] * 5 + r["_collects"] * 2 + r["_shares"] * 3
    records.sort(key=lambda r: r["_likes"], reverse=True)

    manifest = []
    for idx, r in enumerate(records, 1):
        manifest.append({
            "rank": idx, "aweme_id": r["aweme_id"],
            "title": r.get("desc") or r.get("title") or "",
            "create_time": r.get("create_time"),
            "likes": r["_likes"], "comments": r["_comments"],
            "collects": r["_collects"], "shares": r["_shares"],
            "video_url": r.get("video_download_url") or "",
            "cover_url": r.get("cover_url") or "",
            "music_url": r.get("music_download_url") or "",
        })

    mpath = os.path.join(outdir, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[去重] 唯一视频数: {len(records)}")
    print(f"[OK] manifest.json -> {mpath}")
    print(f"[下载] 有视频URL {sum(1 for m in manifest if m['video_url'])} / 缺失 {sum(1 for m in manifest if not m['video_url'])}")


if __name__ == "__main__":
    main()
