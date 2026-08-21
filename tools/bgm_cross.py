# -*- coding: utf-8 -*-
"""Cross stats for BGM candidates in mixed-track non-speech windows.

Only records with enough transcript-masked audio evidence are included in the
denominator. Group differences are descriptive associations, not causal claims.
"""
import argparse
import glob
import json
import os
import tempfile


def _avg(ids, manifest_by_id, field):
    values = [float(manifest_by_id[aid].get(field) or 0) for aid in ids]
    return round(sum(values) / len(values), 1) if values else 0.0


def _write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path),
                                        prefix="._cross-", suffix=".tmp", delete=False) as f:
            tmp = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _sys_exit(msg):
    import sys
    sys.exit(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    mf_p = os.path.join(a.root, "video-analysis", a.account, "manifest.json")
    if not os.path.isfile(mf_p):
        _sys_exit(f"[ERR] 缺 manifest: {mf_p}（先跑 process.py）")
    manifest = json.load(open(mf_p, encoding="utf-8"))
    inter = {str(r["aweme_id"]): r for r in manifest if int(r.get("aweme_type") or 0) != 68}
    manifest_by_id = inter

    bgmd = {}
    bgm_dir = os.path.join(a.root, "bgm", a.account)
    for f in glob.glob(os.path.join(bgm_dir, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        j = json.load(open(f, encoding="utf-8"))
        if str(j.get("source_kind")) != "mixed_track":
            _sys_exit(f"[ERR] BGM 归档 {f} 不是 published mixed track 新契约，请重跑 transcribe_bgm.py")
        if j.get("cache_version") != "published-mixed-track-bgm-v3":
            _sys_exit(f"[ERR] BGM 归档 {f} 使用旧 cache version，请重跑 transcribe_bgm.py")
        bgmd[str(j["aweme_id"])] = j
    if not bgmd:
        _sys_exit(f"[ERR] 无混合音轨 BGM 归档: {bgm_dir}（先跑 transcribe_bgm.py）")
    missing = sorted(set(inter) - set(bgmd))
    if missing:
        preview = ",".join(missing[:10]) + ("..." if len(missing) > 10 else "")
        _sys_exit(f"[ERR] 混合音轨 BGM 归档不完整: 缺 {len(missing)}/{len(inter)} 个视频（{preview}）")

    def _analysis_status(record):
        # New records are authoritative; source_status remains a legacy alias.
        return record.get("analysis_status") or record.get("source_status") or "unknown"

    evidence = {aid: b for aid, b in bgmd.items()
                if aid in inter and _analysis_status(b) == "ok"
                and b.get("source_kind") == "mixed_track"
                and b.get("analysis_scope") == "non_speech_windows"
                and b.get("non_speech_seconds", 0) >= 3.0
                and b.get("non_speech_coverage", 0) >= 0.10
                and b.get("bgm_level") in ("none", "light", "full")}
    excluded = {aid: _analysis_status(b) for aid, b in bgmd.items() if aid not in evidence}
    n = len(evidence)
    groups = {
        "by_level": ["bgm_level", {"none": "无明确 BGM 候选", "light": "轻度 BGM 候选", "full": "强度 BGM 候选"}],
        "by_mood": ["mood", None],
        "by_vocal": ["vocal", None],
    }
    out = {"cache_version": "published-mixed-track-bgm-v3", "source_kind": "mixed_track",
           "analysis_scope": "non_speech_windows", "n": n,
           "total_video_records": len(inter), "excluded_records": len(excluded),
           "excluded_status": {}, "limitations": ["仅统计足够非口播窗口证据；组间差异为相关非因果"]}
    for status in excluded.values():
        out["excluded_status"][status] = out["excluded_status"].get(status, 0) + 1

    for key, (field, labels) in groups.items():
        grouped = {}
        for aid, record in evidence.items():
            grouped.setdefault(record.get(field, "unknown"), []).append(aid)
        stat = {}
        for value, ids in grouped.items():
            stat[value] = {
                "n": len(ids),
                "pct": round(len(ids) * 100 / n, 1) if n else 0.0,
                "avg_likes": _avg(ids, manifest_by_id, "likes"),
                "avg_collects": _avg(ids, manifest_by_id, "collects"),
                "avg_shares": _avg(ids, manifest_by_id, "shares"),
                "label": (labels or {}).get(value, value) if labels else value,
            }
        out[key] = stat

    top = sorted((manifest_by_id[aid] for aid in evidence),
                 key=lambda r: r.get("likes", 0), reverse=True)[:max(0, a.top)]
    out["top_n"] = [{"aweme_id": str(r["aweme_id"]), "likes": r.get("likes", 0),
                      "bgm_level": evidence[str(r["aweme_id"])].get("bgm_level", "unknown"),
                      "mood": evidence[str(r["aweme_id"])].get("mood", "unknown"),
                      "vocal": evidence[str(r["aweme_id"])].get("vocal", "unknown"),
                      "non_speech_seconds": evidence[str(r["aweme_id"])].get("non_speech_seconds", 0)}
                     for r in top]

    def _mult(num, den):
        return round(num / den, 3) if den else None

    levels = out["by_level"]
    no, light = levels.get("none"), levels.get("light")
    if no and light:
        summary = {
            "light_candidate_vs_none_candidate_like_mult": _mult(light["avg_likes"], no["avg_likes"]),
            "light_candidate_vs_none_candidate_collect_mult": _mult(light["avg_collects"], no["avg_collects"]),
            "light_candidate_vs_none_candidate_share_mult": _mult(light["avg_shares"], no["avg_shares"]),
        }
        out["summary"] = {k: v for k, v in summary.items() if v is not None}

    op = os.path.join(bgm_dir, "_cross.json")
    _write_json_atomic(op, out)
    print(f"[bgm_cross] {a.account}: evidence_n={n} excluded={len(excluded)} top={len(out['top_n'])}")
    if out.get("summary"):
        print("  轻度候选/无明确候选 " + " ".join(f"{k}={v}" for k, v in out["summary"].items()))
    print(f"[manifest] {op}")


if __name__ == "__main__":
    main()
