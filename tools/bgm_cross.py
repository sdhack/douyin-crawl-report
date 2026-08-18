# -*- coding: utf-8 -*-
"""BGM × 互动交叉统计：合并 manifest + BGM 归档 → 组间均值与爆款明细。

供报告的"BGM 视听分析"章节取实证数字（勿手写/臆断）。输出:
  <root>/bgm/<account>/_cross.json
    by_level / by_mood / by_vocal : 每组 {n, pct, avg_likes, avg_collects, avg_shares}
    top_n                          : 按赞排序前 N 条的 {aweme_id, likes, bgm_level, mood, vocal}
    summary                        : 关键对比（纯口播 vs 轻BGM 的均赞倍数 等）
用法: python tools/bgm_cross.py --root <工作根> --account <slug> [--top 10]
输入依赖: <root>/video-analysis/<account>/manifest.json（process.py 产出）
          <root>/bgm/<account>/*.json（transcribe_bgm.py 产出）
"""
import argparse, os, json, glob


def _avg(d, col):
    x = list(col.items())
    return round(sum(col[a] for a in d) / len(d), 1) if d else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    mf_p = os.path.join(a.root, "video-analysis", a.account, "manifest.json")
    if not os.path.isfile(mf_p):
        sys_exit(f"[ERR] 缺 manifest: {mf_p}（先跑 process.py）")
    manifest = json.load(open(mf_p, encoding="utf-8"))
    inter = {r["aweme_id"]: r for r in manifest}

    bgmd = {}
    for f in glob.glob(os.path.join(a.root, "bgm", a.account, "*.json")):
        if "_manifest" in os.path.basename(f):
            continue
        j = json.load(open(f, encoding="utf-8"))
        bgmd[j["aweme_id"]] = j
    if not bgmd:
        sys_exit(f"[ERR] 无 BGM 归档: <root>/bgm/{a.account}/（先跑 transcribe_bgm.py）")

    groups = {"by_level": ["bgm_level", {"none": "纯口播/无BGM", "light": "轻BGM垫底", "full": "强BGM"}],
              "by_mood": ["mood", None],
              "by_vocal": ["vocal", None]}
    out, out["n"] = {}, len(inter)
    for key, (field, labels) in groups.items():
        g = {}
        for aid, r in inter.items():
            b = bgmd.get(aid)
            if not b:
                continue
            g.setdefault(b.get(field, "?"), []).append(aid)
        stat = {}
        for val, ids in g.items():
            stat[val] = {
                "n": len(ids),
                "pct": round(len(ids) * 100 / len(inter), 1),
                "avg_likes": _avg(ids, {aid: inter[aid].get("likes", 0) for aid in inter}),
                "avg_collects": _avg(ids, {aid: inter[aid].get("collects", 0) for aid in inter}),
                "avg_shares": _avg(ids, {aid: inter[aid].get("shares", 0) for aid in inter}),
                "label": (labels or {})[val] if labels else val,
            }
        out[key] = stat

    top = sorted(inter.values(), key=lambda r: r.get("likes", 0), reverse=True)[:a.top]
    out["top_n"] = [{
        "aweme_id": r["aweme_id"], "likes": r.get("likes", 0),
        "bgm_level": bgmd.get(r["aweme_id"], {}).get("bgm_level", "?"),
        "mood": bgmd.get(r["aweme_id"], {}).get("mood", "?"),
        "vocal": bgmd.get(r["aweme_id"], {}).get("vocal", "?"),
    } for r in top]

    # summary：关键对比
    L = out["by_level"]
    no, lt = L.get("none"), L.get("light")
    if no and lt:
        out["summary"] = {
            "light_vs_none_like_mult": round(lt["avg_likes"] / no["avg_likes"], 1),
            "light_vs_none_collect_mult": round(lt["avg_collects"] / no["avg_collects"], 1),
            "light_vs_none_share_mult": round(lt["avg_shares"] / no["avg_shares"], 1),
        }

    op = os.path.join(a.root, "bgm", a.account, "_cross.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[bgm_cross] {a.account}: n={out['n']} top={len(out['top_n'])}")
    if "summary" in out:
        s = out["summary"]
        print(f"  轻BGM/纯口播 均赞×{s['light_vs_none_like_mult']} 收藏×{s['light_vs_none_collect_mult']} 分享×{s['light_vs_none_share_mult']}")
    print(f"[manifest] {op}")

def sys_exit(msg):
    import sys
    sys.exit(msg)

if __name__ == "__main__":
    main()