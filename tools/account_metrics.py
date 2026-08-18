# -*- coding: utf-8 -*-
"""账号级自动聚合：从 video_profiles.json 直接产出 3 个"采集了就必须分析"的维度。

输入  decompose/<account>/video_profiles.json（每视频：title/create_time/likes/collects/
        shares/comment_n/comments[{} like_count..]/duration_sec）
输出  decompose/<account>/_metrics.json + 控制台摘要，供 blogger-summary-prompt 引用：
  1) 发布节奏   —— create_time 按自然月计数 + 相邻发布间隔中位/跨度（诚实标注仅日期，无小时）
  2) 互动交叉聚类—— 收藏型(收藏率>赞)/分享型(分享>赞)/讨论型(评论密度高)/爆款型(赞 top) Top5 + 共性提示
  3) 话题策略    —— #hashtag 词频 + 含话题视频均赞，以及全账号 Top 高赞评论原文（含所属标题/点赞）

用法：py -3 <skill>/tools/runtime.py run --tool account_metrics.py --root <根> --account <slug>
"""
import argparse, collections, json, os, re, statistics
from datetime import datetime

HASHTAG = re.compile(r"#([^\s#.，。・·]+)")


def main():
    ap = argparse.ArgumentParser("account_metrics")
    ap.add_argument("--root")
    ap.add_argument("--account")
    a = ap.parse_args()
    if not a.root or not a.account:
        ap.error("需要 --root <根> --account <slug>")
    base = os.path.join(a.root, "decompose", a.account)
    vp = json.load(open(os.path.join(base, "video_profiles.json"), encoding="utf-8"))
    vids = list(vp.values())
    n = len(vids)

    # ---------- 1) 发布节奏 ----------
    dates = sorted(v for v in (v.get("create_time") for v in vids) if v)
    months = collections.Counter()
    chain = [d for d in dates if isinstance(d, str) and len(d) >= 7]
    for d in chain:
        months[d[:7]] += 1
    gaps = []
    prev = None
    for d in chain:
        cur = datetime.strptime(d, "%Y-%m-%d")
        if prev:
            gaps.append((cur - prev).days)
        prev = cur
    tone = {
        "first": chain[0] if chain else None,
        "last": chain[-1] if chain else None,
        "span_days": (datetime.strptime(chain[-1], "%Y-%m-%d") - datetime.strptime(chain[0], "%Y-%m-%d")).days + 1 if len(chain) >= 2 else 0,
        "monthly_avg": round(len(chain) / max(1, len(set(chain[k][:7] for k in range(len(chain))))), 1),
        "top3_months": [{"month": m, "count": c} for m, c in months.most_common(3)],
        "gap_median": (sorted(gaps)[len(gaps) // 2] if gaps else None),
        "note": "create_time 仅到日期、无小时，只能做发布频率/月度节奏，无法判断「几点发」。月均=总量/有发布月份数（断更月不计分母，勿与整跨度月均混淆）。",
    }

    # ---------- 2) 互动交叉聚类 ----------
    rows = []
    for v in vids:
        L = v.get("likes", 0) or 0
        C = v.get("collects", 0) or 0
        S = v.get("shares", 0) or 0
        M = v.get("comment_n", 0) or 0
        rows.append({
            "title": v.get("title", "")[:26], "likes": L, "collects": C, "shares": S,
            "comments": M, "dur": v.get("duration_sec"),
        })
    def rankmap(key):
        order = sorted(range(len(rows)), key=lambda i: -rows[i][key])
        ranks = [0] * len(rows)
        for rank, idx in enumerate(order, 1):
            ranks[idx] = rank
        return ranks
    likes_r = rankmap("likes"); coll_r = rankmap("collects")
    shr_r = rankmap("shares"); cmt_r = rankmap("comments")
    def adv(i, dm):
        # 相对突出度：点赞排名 / 该维度排名。排名值越小越靠前，故 >1 表示该维度比点赞更靠前（更突出）。
        return likes_r[i] / max(dm[i], 1)
    def fmt(rs):
        return [{"赞": r["likes"], "藏": r["collects"], "评": r["comments"], "享": r["shares"], "标题": r["title"]}
                for r in rs]
    def nzmed(k):
        vals = [r[k] for r in rows if r[k] > 0]
        return statistics.median(vals) if vals else 0
    cm = nzmed("collects"); sm = nzmed("shares"); mm = nzmed("comments")
    def top_by(field, med, thr, dm):
        cand = [i for i, r in enumerate(rows) if r[field] >= med and adv(i, dm) > thr]
        cand.sort(key=lambda i: adv(i, dm) * rows[i][field] / (med + 1), reverse=True)
        return [rows[i] for i in cand][:5]
    collect_hold = top_by("collects", cm, 1.3, coll_r)
    share_more = top_by("shares", sm, 1.3, shr_r)
    discuss = top_by("comments", mm, 1.4, cmt_r)
    crs = [r["collects"] / r["likes"] for r in rows if r["likes"] > 0]
    srs = [r["shares"] / r["likes"] for r in rows if r["likes"] > 0]
    mrs = [r["comments"] / r["likes"] for r in rows if r["likes"] > 0]
    top1 = max(r["likes"] for r in rows); total = sum(r["likes"] for r in rows)
    structure = {
        "口径": "互动以点赞为主体时，收藏/评论率越低越偏向纯点赞型",
        "分享率中位": round(statistics.median(srs), 3) if srs else 0,
        "收藏率中位": round(statistics.median(crs), 3) if crs else 0,
        "评论率中位": round(statistics.median(mrs), 3) if mrs else 0,
        "最高赞单条占比": "%d%%" % round(top1 / total * 100),
        "解读": "三个比率越低 = 互动越集中在点赞/浏览，评论区与收藏驱动弱（结合讨论型是否命中判断存在性）",
    }
    interact = {
        "口径": "相对突出度=点赞排名/该维度排名（排名值越小越靠前，比值>1 即该维度比点赞更靠前=更突出）；收藏型=收藏排名比点赞靠前、分享型=分享排名比点赞靠前、讨论型=评论密度突出；爆款型=赞 top5；阈值用账号自适应中位数",
        "整体互动结构": structure,
        "爆款型_Top": fmt(sorted(rows, key=lambda r: -r["likes"])[:5]),
        "收藏型_Top": fmt(collect_hold),
        "讨论型_Top": fmt(discuss),
        "分享转执型_Top": fmt(share_more),
    }

    # ---------- 3) 话题策略 + 高赞评论 ----------
    tag_c = collections.Counter()
    tag_like = collections.Counter()
    for v in vids:
        text = (v.get("title") or "") + "\n" + (v.get("transcript") or v.get("desc") or "")
        tags = set(HASHTAG.findall(text))
        L = v.get("likes", 0) or 0
        for t in tags:
            tag_c[t] += 1
            tag_like[t] += L
    topic = [
        {"话题": t, "次数": tag_c[t], "均赞": round(tag_like[t] / tag_c[t])}
        for t, _ in tag_c.most_common(15)
    ] if tag_c else []

    hot = []
    for v in vids:
        for c in (v.get("comments") or []):
            hot.append({
                "赞": c.get("like_count", 0) or 0, "内容": (c.get("content") or "")[:48],
                "昵称": c.get("nickname", ""), "视频": (v.get("title") or "")[:18],
            })
    hot.sort(key=lambda x: -x["赞"])
    top_comments = hot[:20]

    result = {
        "account": a.account, "count": n,
        "发布节奏": tone, "互动交叉聚类": interact,
        "话题策略": topic, "高赞评论Top20": top_comments,
    }
    out_path = os.path.join(base, "_metrics.json")
    open(out_path, "w", encoding="utf-8").write(json.dumps(result, ensure_ascii=False, indent=2))
    print("已生成 _metrics.json：", out_path)
    print("\n== 节奏 ==", tone["first"], "→", tone["last"], "| 跨度", tone["span_days"], "天 | 月均",
          tone["monthly_avg"], "| 间隔中位", tone["gap_median"], "天 | 峰值", tone["top3_months"])
    print("== 互动聚类 == 爆款%d 收藏型%d 讨论型%d 分享转执%d（Top 各5）" % (
        len(interact["爆款型_Top"]), len(interact["收藏型_Top"]),
        len(interact["讨论型_Top"]), len(interact["分享转执型_Top"])))
    print("== 话题 Top5 ==", [(x["话题"], x["次数"]) for x in topic[:5]])
    print("== 高赞评论 Top5 ==")
    for x in top_comments[:5]:
        print("  赞%4d | %s" % (x["赞"], x["内容"]))


if __name__ == "__main__":
    main()