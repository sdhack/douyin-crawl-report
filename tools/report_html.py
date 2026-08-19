# -*- coding: utf-8 -*-
"""对标分析报告 · 固定骨架 HTML 生成器（v2 模板，技能内建）。

骨架与视觉系统恒定固化（对齐 references/report-template.md v2）：
  文档头(masthead+meta) → 侧栏导航 → s0 数据构成 → s1 核心结论 → s2 对标方法
  → s3 达人画像 → s4 内容矩阵 → s5 文案拆解 → s6 评论区实证 → s7 BGM×互动
  → s8 变现逻辑 → s9 起号方案 → 诚实口径附言
所有数字实时从管线产物计算（manifest / comments / bgm _cross / frames / covers /
transcript 目录），杜绝手写数字与数据漂移；定性结论经 --narrative JSON 提供，
未提供的定性槽位整块省略并记入附言「缺源」，绝不虚构。

图片规则：TOP 榜内联真实封面（covers/<account>/<aid>.jpg），爆款区内联真实关键帧
（video-analysis/<account>/frames/<aid>/ 中位帧），超 --img-cap-kb(默认400KB) 自动跳过；
缺图如实标注，禁止 AI 生成图。

用法（统一经 tools/runtime.py run --tool report_html.py -- …）：
  python tools/report_html.py --root <工作根> --account <slug> \
      --title "抖音XX达人对标分析报告" --subtitle "「账号」拆解与起号方案" \
      --narrative narrative.json --out 对标分析报告.html
"""
import argparse
import base64
import json
import os
import re
from collections import Counter
from datetime import datetime

# ---------------- 图标系统（SVG，自动插入标题/卡片/导航） ----------------
ICONS = {
    "video": '<path d="M4 6h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z M16 10l4-3v10l-4-3"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0 M12 18v3 M8 21h8"/>',
    "music": '<path d="M9 18V5l10-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="19" cy="16" r="3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "fire": '<path d="M12 22c4 0 7-2.7 7-7 0-3-2-5.5-3.5-7C15 6.5 13 5 12 2c0 3-2 4.5-3.5 6C7 9.5 5 12 5 15c0 4.3 3 7 7 7z"/>',
    "chart": '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="5" width="3" height="13"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "tag": '<path d="M20 12l-8 8-9-9V3h8z"/><circle cx="7" cy="7" r="1.5"/>',
    "cart": '<circle cx="9" cy="20" r="1.5"/><circle cx="17" cy="20" r="1.5"/><path d="M3 3h2l2.5 12h11L21 7H6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "quote": '<path d="M10 8c-3 0-5 2-5 5s2 4 4 4 3-1 3-3-1-3-3-3c0-2 1-3 3-3zM20 8c-3 0-5 2-5 5s2 4 4 4 3-1 3-3-1-3-3-3c0-2 1-3 3-3z"/>',
}
ICON_RULES = [
    ("画像|基本盘|互动特征|分布|指标", "chart"),
    ("发布|时段|规律|节奏", "clock"),
    ("爆款|TOP|最高|公式", "fire"),
    ("主题|矩阵|结构|标签", "tag"),
    ("标题|文案|金句|话术|句式|口号", "quote"),
    ("语料|逐字稿|转写|口播", "mic"),
    ("CTA|钩子|评论|私信|留言", "chat"),
    ("BGM|音乐|音源|歌词", "music"),
    ("变现|带货|产品|直播|SKU|定价", "cart"),
    ("起号|方案|切入点|缺口|弱点|对标", "target"),
    ("合规|红线|风险|边界", "shield"),
    ("帧|画面|封面|视觉", "image"),
]

def icon(name, size=18):
    return ('<svg class="ic" width="%d" height="%d" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round">%s</svg>' % (size, size, ICONS[name]))

def icon_for(text):
    for pat, name in ICON_RULES:
        if re.search(pat, text):
            return icon(name)
    return icon("target")

# ---------------- 主题分类（标题关键词规则，可经 narrative.theme_rules 覆盖） ----------------
DEFAULT_THEME_RULES = [
    ("打假/避坑", ["智商税", "避坑", "别再", "套路", "骗局", "割韭菜", "别买", "劝退"]),
    ("测评对比", ["测评", "对比", "横评", "怎么选", "排行榜", "红黑榜"]),
    ("使用/体验", ["体验", "打卡", "记录", "日常", "开箱", "分享"]),
    ("科普/成分", ["成分", "原料", "工艺", "工厂", "溯源", "配方", "科普", "知识", "避雷"]),
]

DEFAULT_COMMENT_PATTERNS = {
    "身体状态描述": "皮肤|睡眠|气色|斑|皱|头发|体重",
    "信任/支持": "支持|相信|诚信|信任|良心|靠谱",
    "复购/坚持": "一直喝|回购|坚持|第二盒|第三次|囤",
    "价格/划算": "多少钱|贵|便宜|划算|价格|优惠",
    "购买行动": "下单|已拍|买了|到货|拍了",
    "功效疑问": "管不管用|有用吗|有效果|管用吗|真的有用",
    "质疑/智商税": "智商税|割韭菜|广告|恰饭|剧本|托",
}
WARN_THEMES = ("功效疑问", "质疑/智商税")

def pctile(sorted_vals, p):
    if not sorted_vals:
        return 0
    i = min(len(sorted_vals) - 1, max(0, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[i]

def b64img(path, cap_kb):
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= cap_kb * 1024:
            return "data:image/jpeg;base64," + base64.b64encode(open(path, "rb").read()).decode()
    except OSError:
        pass
    return ""

def hbar(pct, label, val, color):
    return ('<div class="hbar"><span class="hb-l">%s</span><div class="hb-track">'
            '<div class="hb-fill" style="width:%.1f%%;background:%s"></div></div>'
            '<span class="hb-v">%s</span></div>' % (label, pct, color, val))

CSS = """
:root{--ink:#241f2e;--ink-70:#4a4358;--ink-30:#a9a3b8;--paper:#faf7f4;--card:#fff;
--line:#e8e2ec;--rose:#d95f7f;--rose-bg:#fbeef2;--gold:#b98a3c;--gold-bg:#f7f0e3;
--serif:"Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--paper);color:var(--ink);line-height:1.75}
.page{max-width:1080px;margin:0 auto;padding:0 28px 80px}
.ic{vertical-align:-3px}
.masthead{padding:64px 0 36px;border-bottom:3px solid var(--ink)}
.kicker{font-size:13px;letter-spacing:3px;color:var(--rose);font-weight:600;text-transform:uppercase;margin-bottom:14px}
h1{font-family:var(--serif);font-size:38px;font-weight:700;letter-spacing:1px}
.subtitle{font-family:var(--serif);font-size:17px;color:var(--ink-70);margin-top:8px;font-style:italic}
.meta-line{display:flex;gap:22px;flex-wrap:wrap;margin-top:22px;font-size:13px;color:var(--ink-70)}
.meta-line span{display:flex;align-items:center;gap:6px}
nav{position:sticky;top:0;z-index:50;background:rgba(250,247,244,.95);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:12px 0;margin-bottom:36px}
nav .nav-in{display:flex;gap:6px;flex-wrap:wrap}
nav a{font-size:13px;color:var(--ink-70);text-decoration:none;padding:5px 12px;border-radius:20px;border:1px solid transparent;transition:.2s}
nav a:hover{color:var(--rose);border-color:var(--rose)}
.intro{display:grid;grid-template-columns:1.5fr 1fr;gap:28px;margin-bottom:40px}
.intro p{color:var(--ink-70);font-size:14.5px}
.pill-box{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;align-self:start}
.pill-box h4{font-size:13px;color:var(--gold);margin-bottom:10px;letter-spacing:1px}
.pill{display:inline-block;font-size:12.5px;background:var(--rose-bg);color:var(--rose);padding:3px 11px;border-radius:14px;margin:0 6px 8px 0}
.samples{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:44px}
.sample{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 16px;text-align:center}
.sample .ic{color:var(--rose)}
.sample b{display:block;font-family:var(--serif);font-size:26px;margin:8px 0 2px}
.sample small{color:var(--ink-30);font-size:12px;line-height:1.5;display:block}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:8px 0 40px}
.stat{background:var(--ink);color:#fff;border-radius:14px;padding:20px 18px}
.stat b{font-family:var(--serif);font-size:30px;display:block}
.stat small{color:#b8b0c9;font-size:12px}
section{margin-bottom:52px}
h2{font-family:var(--serif);font-size:25px;padding-left:14px;border-left:4px solid var(--rose);margin-bottom:6px}
.sec-sub{color:var(--ink-30);font-size:13px;margin-bottom:20px;padding-left:18px}
h3{font-size:17px;margin:26px 0 12px;display:flex;align-items:center;gap:8px}
h3 .ic{color:var(--gold)}
p{margin-bottom:12px;font-size:14.5px}
.note{background:var(--gold-bg);border-left:3px solid var(--gold);padding:12px 16px;border-radius:0 10px 10px 0;font-size:13px;color:var(--ink-70);margin:14px 0}
.note b{color:var(--gold)}
.ki{background:var(--rose-bg);border-left:3px solid var(--rose);padding:12px 16px;border-radius:0 10px 10px 0;font-size:13.5px;margin:14px 0}
.ki b{color:var(--rose)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13.5px;margin:14px 0}
th{background:var(--ink);color:#fff;padding:10px 12px;text-align:left;font-weight:500;font-size:12.5px;letter-spacing:.5px}
td{padding:9px 12px;border-top:1px solid var(--line);vertical-align:middle}
tr.hot td{background:var(--rose-bg)}
td.num{font-variant-numeric:tabular-nums}
td.dim{color:var(--ink-30);font-size:12.5px}
.mini-cov{width:44px;height:58px;object-fit:cover;border-radius:5px;display:block}
.mini-cov.none{display:flex;align-items:center;justify-content:center;background:var(--line);color:var(--ink-30);font-size:9px}
.mini-bar{height:3px;background:var(--line);border-radius:2px;margin-top:5px;width:90px}
.mini-bar span{display:block;height:100%;background:var(--rose);border-radius:2px}
.t-cell{font-size:12.5px;max-width:300px}
.formula{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}
.fcell{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 12px;font-size:12.5px}
.fcell b{display:block;color:var(--rose);font-size:13.5px;margin-bottom:5px}
.qgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:16px 0}
.qcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;font-size:13px}
.qcard p{font-size:13px;margin:10px 0 8px;color:var(--ink-70)}
.q-top{color:var(--rose);font-size:12px;display:flex;gap:6px;align-items:center}
.q-src{font-size:11.5px;color:var(--ink-30);border-top:1px dashed var(--line);padding-top:8px}
.hbars{margin:14px 0}
.hbar{display:grid;grid-template-columns:110px 1fr 130px;gap:10px;align-items:center;font-size:13px;margin-bottom:9px}
.hb-track{height:10px;background:#efeaf2;border-radius:5px;overflow:hidden}
.hb-fill{height:100%;border-radius:5px}
.hb-v{color:var(--ink-70);font-size:12px;text-align:right}
.fgallery{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:16px 0}
.fcard{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.fcard img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block}
.fcard figcaption{font-size:10.5px;padding:7px 8px;color:var(--ink-70);white-space:nowrap;overflow:hidden}
.chart-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;margin:16px 0}
.chart-card h4{font-size:14px;margin-bottom:4px}
.chart-card .src{font-size:11.5px;color:var(--ink-30);margin-bottom:10px}
.qcols{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:14px 0}
.qgroup{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.qgroup h4{font-size:13.5px;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid var(--rose);display:inline-block}
.qgroup.warn h4{border-color:var(--gold)}
.qgroup ul{list-style:none}
.qgroup li{font-size:12.5px;color:var(--ink-70);padding:8px 0;border-bottom:1px dashed var(--line)}
.q-like{float:right;color:var(--rose);font-size:11px}
.steps{counter-reset:step;margin:14px 0}
.step{display:flex;gap:16px;padding:14px 0;border-bottom:1px dashed var(--line)}
.step::before{counter-increment:step;content:counter(step);min-width:34px;height:34px;border-radius:50%;background:var(--ink);color:#fff;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:16px}
.step h5{font-size:14.5px;margin-bottom:3px}
.step p{font-size:13px;color:var(--ink-70);margin:0}
.checklist{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin:14px 0}
.checklist li{font-size:13.5px;margin:8px 0 8px 4px;list-style:none}
.checklist li::before{content:"✓";color:var(--rose);font-weight:700;margin-right:8px}
footer{border-top:3px solid var(--ink);padding-top:24px;font-size:12px;color:var(--ink-30);line-height:2}
@media(max-width:900px){.samples{grid-template-columns:repeat(2,1fr)}.stats{grid-template-columns:repeat(2,1fr)}.intro{grid-template-columns:1fr}.qgrid,.qcols{grid-template-columns:1fr}.fgallery{grid-template-columns:repeat(3,1fr)}.formula{grid-template-columns:1fr 1fr}}
"""

def load_json(path):
    return json.load(open(path, encoding="utf-8")) if path and os.path.isfile(path) else None

def count_transcripts(root, account):
    d = os.path.join(root, "transcript", account)
    if not os.path.isdir(d):
        return 0
    return sum(len([f for f in fs if f.endswith((".json", ".txt", ".md"))]) for _, _, fs in os.walk(d))

def build(args):
    root, acc = args.root, args.account
    nar = load_json(args.narrative) or {}

    man_p = os.path.join(root, "video-analysis", acc, "manifest.json")
    man = load_json(man_p)
    if not man:
        raise SystemExit("[ERR] 缺 manifest：%s（先跑 process.py）" % man_p)
    comments = load_json(os.path.join(root, "video-analysis", acc, "comments.json"))
    cross = load_json(os.path.join(root, "bgm", acc, "_cross.json"))

    n = len(man)
    bya = {m["aweme_id"]: m for m in man}
    likes_sorted = sorted(m.get("likes", 0) for m in man)
    sum_likes = sum(likes_sorted)
    sum_c = sum(m.get("comments", 0) for m in man)
    sum_col = sum(m.get("collects", 0) for m in man)
    top = sorted(man, key=lambda m: -m.get("likes", 0))
    avg_like = sum_likes / n
    dates = sorted(datetime.fromtimestamp(m["create_time"]) for m in man)
    years = (dates[-1] - dates[0]).days / 365.0

    covers_d = os.path.join(root, "covers", acc)
    frames_d = os.path.join(root, "video-analysis", acc, "frames")
    n_fvids = sum(1 for m in man if os.path.isdir(os.path.join(frames_d, m["aweme_id"])))
    n_frames = 0
    for m in man:
        d = os.path.join(frames_d, m["aweme_id"])
        if os.path.isdir(d):
            n_frames += len([f for f in os.listdir(d) if f.endswith(".jpg")])
    n_tr = count_transcripts(root, acc)

    def cover(aid):
        return b64img(os.path.join(covers_d, aid + ".jpg"), args.img_cap_kb)

    def frame(aid):
        d = os.path.join(frames_d, aid)
        if not os.path.isdir(d):
            return ""
        fs = sorted(f for f in os.listdir(d) if f.endswith(".jpg"))
        return b64img(os.path.join(d, fs[len(fs) // 2]), args.img_cap_kb) if fs else ""

    missing = []
    if not comments:
        missing.append("评论（comments.json）")
    if not cross:
        missing.append("BGM 交叉（_cross.json）")
    if not n_fvids:
        missing.append("关键帧（frames/）")
    if not n_tr:
        missing.append("口播逐字稿（transcript/）")

    # ---- s0 数据构成 ----
    meta_items = ['<span>%s %d 条作品全量</span>' % (icon("video"), n)]
    if n_tr:
        meta_items.append('<span>%s %d 份口播逐字稿</span>' % (icon("mic"), n_tr))
    if comments:
        nc_all = sum(v["n"] for v in comments["by_aweme"].values())
        meta_items.append('<span>%s %s 条评论实证</span>' % (icon("chat"), f"{nc_all:,}"))
    if cross:
        n_bgm = sum(v["n"] for v in cross.get("by_level", {}).values())
        meta_items.append('<span>%s %d 份 BGM 档案</span>' % (icon("music"), n_bgm))
    meta_items.append('<span>%s %d 封面%s</span>' % (icon("image"),
        sum(1 for m in man if os.path.isfile(os.path.join(covers_d, m["aweme_id"] + ".jpg"))),
        (" + %d 视频关键帧" % n_fvids) if n_fvids else "（关键帧缺源）"))

    pills = nar.get("pills") or [
        "视频 %d" % n, "%s – %s" % (dates[0].strftime("%Y-%m"), dates[-1].strftime("%Y-%m")),
        ("评论 %d 视频覆盖" % len(comments["by_aweme"])) if comments else "评论缺源",
        "非抽样全量",
    ]
    intro = nar.get("intro") or ("基于对标账号 %d 条作品的全量数据（作品字段/互动指标/逐字稿/评论/封面/关键帧/BGM 中已具备的源），"
                                 "拆解其内容打法、人设逻辑与变现路径，并输出差异化起号方案。（自动摘要）" % n)

    samples = ['<div class="sample">%s<b>%d</b><small>作品全量<br>（非抽样）</small></div>' % (icon("video", 22), n)]
    if n_tr:
        samples.append('<div class="sample">%s<b>%d</b><small>口播逐字稿<br>（含校对版）</small></div>' % (icon("mic", 22), n_tr))
    if comments:
        nc_all = sum(v["n"] for v in comments["by_aweme"].values())
        samples.append('<div class="sample">%s<b>%s</b><small>真实评论<br>（%d 视频覆盖）</small></div>'
                       % (icon("chat", 22), f"{nc_all:,}", len(comments["by_aweme"])))
    if n_fvids:
        samples.append('<div class="sample">%s<b>%d</b><small>视频关键帧轨<br>（1fps 共 %s 张）</small></div>'
                       % (icon("image", 22), n_fvids, f"{n_frames:,}"))
    if cross:
        n_bgm = sum(v["n"] for v in cross.get("by_level", {}).values())
        samples.append('<div class="sample">%s<b>%d</b><small>BGM 档案<br>（强度+情绪）</small></div>' % (icon("music", 22), n_bgm))

    # ---- s1 核心结论 ----
    rate_c = sum_c * 100.0 / sum_likes if sum_likes else 0
    rate_col = sum_col * 100.0 / sum_likes if sum_likes else 0
    conclusions = nar.get("conclusions")
    if not conclusions:
        conclusions = [
            "（自动摘要）全量 %d 条，时间跨度 %.1f 年，均赞 %.0f、中位 %d。" % (n, years, avg_like, pctile(likes_sorted, 50)),
            "（自动摘要）藏/赞 %.1f%% vs 评/赞 %.1f%%——%s。" % (rate_col, rate_c, "收藏主导（做功课型人群）" if rate_col > rate_c else "评论主导（社交互动型人群）"),
            "（自动摘要）单条最高赞 %s，为账号爆款上限参照。" % f"{likes_sorted[-1]:,}",
            "（自动摘要）定性结论请经 --narrative 提供 conclusions 槽位。",
        ]
    concl_html = "".join("<p>%s</p>" % c for c in conclusions)
    stats1 = ('<div class="stat"><b>%d</b><small>全量作品（非抽样）</small></div>'
              '<div class="stat"><b>%.1f年</b><small>持续运营（%s 起）</small></div>'
              '<div class="stat"><b>%s</b><small>单条最高点赞</small></div>'
              '<div class="stat"><b>%.1f%%</b><small>收藏率（藏/赞）vs 评论率 %.1f%%</small></div>'
              % (n, years, dates[0].strftime("%Y-%m"), f"{likes_sorted[-1]:,}", rate_col, rate_c))

    # ---- s2 对标方法（固定五步法骨架） ----
    steps_data = nar.get("benchmark_steps") or [
        {"t": "全量数据采集", "d": "经 MediaCrawler 抓取账号作品全量（本例 %d 条），产出字段+互动基表；只采爆款会失真。" % n},
        {"t": "口播逐字稿化", "d": "%s视频音频转写为逐字稿——只看标题看不到「怎么卖」。" % ("已产出 %d 份；" % n_tr if n_tr else "逐字稿缺源；")},
        {"t": "画像与内容拆解", "d": "互动分布、发布规律、主题矩阵、爆款归因。"},
        {"t": "变现路径拆解", "d": "从口播与评论提取产品线、价格叙事、直播导流话术。"},
        {"t": "持续追踪迭代", "d": "定期增量抓取对比互动迁移；建立 3-5 个对标池账号。"},
    ]
    steps2 = "".join('<div class="step"><div><h5>%s</h5><p>%s</p></div></div>' % (s["t"], s["d"]) for s in steps_data)

    # ---- s3 画像 ----
    year_cnt = Counter(d.year for d in dates)
    yrs = " / ".join("%d:%d" % (y, c) for y, c in sorted(year_cnt.items()))
    p50, p90 = pctile(likes_sorted, 50), pctile(likes_sorted, 90)
    extra_rows = [(str(r[0]), str(r[1]), str(r[2])) for r in nar.get("profile_rows", [])]
    profile_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td class="dim">%s</td></tr>' % r for r in [
            ("作品总量", "%d 条（全量非抽样）" % n, "内容库足够矩阵拆解"),
            ("活跃周期", "%s – %s" % (dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")), "以 manifest 实测为准"),
            ("年发布量", yrs, "低频高质/高频流量型以实测为准"),
            ("平均互动", "赞 %.0f / 藏 %.0f / 评 %.0f / 转 %.0f" % (avg_like, sum_col / n, sum_c / n, sum(m.get("shares", 0) for m in man) / n), "藏评结构见 2.2"),
            ("点赞分布", "P50=%d · P90=%d · 最高 %s" % (p50, p90, f"{likes_sorted[-1]:,}"), "长尾稳、爆款偶发"),
        ] + extra_rows)

    hours = Counter(d.hour for d in dates)
    wds = Counter(d.weekday() for d in dates)
    hmax = max(hours.values()) if hours else 1
    hour_svg = ""
    for h in range(24):
        v = hours.get(h, 0)
        if not v:
            continue
        bh = v / hmax * 100
        color = "var(--gold)" if v == hmax else "var(--rose)" if v >= hmax * 0.6 else "var(--ink-30)"
        hour_svg += ('<rect x="%d" y="%.1f" width="16" height="%.1f" rx="3" fill="%s"><title>%d:00 · %d条</title></rect>'
                     '<text x="%d" y="124" text-anchor="middle" font-size="8" fill="#8a8494">%d</text>'
                     % (h * 25 + 8, 110 - bh * 0.9, bh * 0.9, color, h, v, h * 25 + 16, h))
    wd_names = "一二三四五六日"
    peak_wd, low_wd = max(wds, key=wds.get), min(wds, key=wds.get)
    peak_h = max(hours, key=hours.get) if hours else 0
    s3_auto = ("发布高峰 %d 点档（%d 条），周%s 最勤（%d 条）、周%s 最少（%d 条）。"
               % (peak_h, hours[peak_h], wd_names[peak_wd], wds[peak_wd], wd_names[low_wd], wds[low_wd]))

    # ---- s4 内容矩阵 ----
    rules = [(str(lbl), [str(k) for k in kws]) for lbl, kws in (nar.get("theme_rules") or DEFAULT_THEME_RULES)]
    def theme_of(m):
        t = m.get("title") or ""
        for label, kws in rules:
            if any(k in t for k in kws):
                return label
        return "其他/未分类"
    tstat = {}
    for m in man:
        k = theme_of(m)
        d = tstat.setdefault(k, {"n": 0, "likes": 0, "c": 0, "col": 0})
        d["n"] += 1
        d["likes"] += m.get("likes", 0)
        d["c"] += m.get("comments", 0)
        d["col"] += m.get("collects", 0)
    order = [lbl for lbl, _ in rules if lbl in tstat] + (["其他/未分类"] if "其他/未分类" in tstat else [])
    tmax = max(v["n"] for v in tstat.values()) if tstat else 1
    roles = nar.get("theme_roles") or {}
    theme_rows = ""
    for k in order:
        v = tstat[k]
        hot = ' class="hot"' if v["likes"] / v["n"] > avg_like * 2 else ""
        theme_rows += ('<tr%s><td><b>%s</b><div class="mini-bar"><span style="width:%d%%"></span></div></td>'
                       '<td>%d</td><td>%.1f%%</td><td><b>%.0f</b></td><td>%.0f</td><td>%.0f</td><td class="dim">%s</td></tr>'
                       % (hot, k, v["n"] * 100 // tmax, v["n"], v["n"] * 100.0 / n,
                          v["likes"] / v["n"], v["c"] / v["n"], v["col"] / v["n"], roles.get(k, "")))

    top_rows = ""
    for m in top[:args.top_n]:
        d = datetime.fromtimestamp(m["create_time"]).strftime("%Y-%m-%d")
        cv = cover(m["aweme_id"])
        img = '<img class="mini-cov" src="%s" alt="">' % cv if cv else '<span class="mini-cov none">无封面</span>'
        top_rows += ('<tr><td>%s</td><td class="num"><b>%s</b></td><td class="num">%s</td>'
                     '<td class="num">%s</td><td class="num">%s</td><td class="dim">%s</td><td class="t-cell">%s</td></tr>'
                     % (img, f"{m.get('likes',0):,}", f"{m.get('collects',0):,}", f"{m.get('comments',0):,}",
                        f"{m.get('shares',0):,}", d, (m.get("title") or "")[:38]))

    frame_cards, nf = "", 0
    for m in top:
        f = frame(m["aweme_id"])
        if f:
            frame_cards += ('<figure class="fcard"><img src="%s" alt="关键帧"><figcaption>%s %s · %s</figcaption></figure>'
                            % (f, icon("fire", 12), f"{m.get('likes',0):,}", (m.get("title") or "")[:16]))
            nf += 1
            if nf >= args.frames_n:
                break
    formula_html = "".join('<div class="fcell"><b>%s</b>%s</div>' % (c["t"], c["d"]) for c in nar.get("formula", []))

    # ---- s6 评论区实证 ----
    sec6 = ""
    if comments:
        by = comments["by_aweme"]
        allc = sorted(((c["like_count"], c["content"], aid) for aid, v in by.items() for c in v["comments"]),
                      key=lambda x: -x[0])
        nc, nv = len(allc), len(by)
        pats = nar.get("comment_patterns") or DEFAULT_COMMENT_PATTERNS
        themes = [(k, sum(1 for _, t, _ in allc if re.search(p, t))) for k, p in pats.items()]
        theme_bars = "".join(hbar(v * 100.0 / nc if nc else 0, k, "%d条 · %.1f%%" % (v, v * 100.0 / nc if nc else 0),
                                  "var(--gold)" if k in WARN_THEMES else "var(--rose)") for k, v in themes)
        comment_cards = "".join(
            '<div class="qcard"><div class="q-top">%s <b>%d</b> 赞</div><p>%s</p><div class="q-src">↳ 视频『%s』</div></div>'
            % (icon("quote", 14), lk, t[:80], ((bya.get(aid, {}).get("title")) or "")[:20]) for lk, t, aid in allc[:6])

        def pick(pat, k=4, minlen=8):
            return [(lk, t) for lk, t, _ in allc if len(t) >= minlen and re.search(pat, t)][:k]
        groups = nar.get("comment_groups") or {
            "功效疑问": pick(pats.get("功效疑问", "有用吗|有效果")),
            "质疑/智商税": pick(pats.get("质疑/智商税", "智商税|广告|托"), 3),
            "复购/行动宣言": pick(pats.get("复购/坚持", "回购|下单|买了"), 4),
        }
        qcols = ""
        for gname, samples_g in groups.items():
            if not samples_g:
                continue
            warn = ' warn' if any(w in gname for w in WARN_THEMES) else ''
            qs = "".join('<li>"%s"<span class="q-like">%s %d</span></li>' % (t[:66], icon("fire", 11), lk) for lk, t in samples_g)
            qcols += '<div class="qgroup%s"><h4>%s</h4><ul>%s</ul></div>' % (warn, gname, qs)
        note6 = nar.get("s6_note") or "规则匹配可重复复现；一条评论只计入首个命中主题。截断上限见 comments.json 各视频 max 字段。"
        top_theme = max(themes, key=lambda x: x[1])[0] if themes else "-"
        sec6 = f'''
<section id="s6"><h2>05 · 评论区实证</h2>
<div class="sec-sub">{nc:,} 条真实评论 · {nv} 视频覆盖 · 均 {nc / nv if nv else 0:.1f} 条/视频</div>
<div class="stats">
<div class="stat"><b>{nc:,}</b><small>评论总量（按赞截断口径）</small></div>
<div class="stat"><b>{nv}</b><small>覆盖视频数（{nv * 100.0 / n:.1f}%）</small></div>
<div class="stat"><b>{allc[0][0] if allc else 0}</b><small>最高赞评论</small></div>
<div class="stat"><b>{top_theme}</b><small>最大主题池</small></div>
</div>
<h3>{icon('chart')} 5.1 评论主题分布</h3><div class="hbars">{theme_bars}</div>
<div class="note"><b>口径：</b>{note6}</div>
<h3>{icon('quote')} 5.2 高赞评论 Top6（原声）</h3><div class="qgrid">{comment_cards}</div>
<h3>{icon('target')} 5.3 决策摩擦原声分组</h3><div class="qcols">{qcols}</div>
{('<div class="ki">' + nar["s6_ki"] + "</div>") if nar.get("s6_ki") else ""}
</section>'''

    # ---- s7 BGM×互动 ----
    sec7 = ""
    if cross:
        L = cross.get("by_level", {})
        rows7 = ""
        for k, label in (("none", "纯口播/无BGM"), ("light", "轻BGM垫底"), ("full", "强BGM")):
            if k not in L:
                continue
            v = L[k]
            rows7 += ('<tr><td><b>%s</b></td><td>%d</td><td>%.1f%%</td><td><b>%.0f</b></td><td>%.0f</td><td>%.0f</td></tr>'
                      % (v.get("label") or label, v["n"], v["pct"], v["avg_likes"], v["avg_collects"], v["avg_shares"]))
        s = cross.get("summary", {})
        mult = ("轻 BGM 比纯口播均赞 ×%s、收藏 ×%s、分享 ×%s。"
                % (s.get("light_vs_none_like_mult", "-"), s.get("light_vs_none_collect_mult", "-"),
                   s.get("light_vs_none_share_mult", "-"))) if s else ""
        moods = cross.get("by_mood", {})
        best_mood = max(moods, key=lambda k: moods[k]["avg_likes"]) if moods else ""
        mood_line = ("情绪维度：「%s」均赞最高（%.0f）。" % (best_mood, moods[best_mood]["avg_likes"])) if best_mood else ""
        sec7 = f'''
<section id="s7"><h2>06 · BGM × 互动交叉</h2>
<div class="sec-sub">BGM 归档与互动指标的组间统计（数字取自 _cross.json，勿手写）</div>
<table><tr><th>BGM 强度</th><th>条数</th><th>占比</th><th>均赞</th><th>均藏</th><th>均转</th></tr>{rows7}</table>
<p>{mood_line}{mult}</p>
{('<div class="ki">' + nar["s7_ki"] + "</div>") if nar.get("s7_ki") else ""}
</section>'''

    # ---- s5 文案 / s8 变现 / s9 起号（全定性，narrative 驱动，缺则整章省略） ----
    sec5 = ""
    if nar.get("s4"):
        s4 = nar["s4"]
        stats4 = "".join('<div class="stat"><b>%s</b><small>%s</small></div>' % (c["b"], c["s"]) for c in s4.get("stats", []))
        slogan_rows = "".join('<tr><td><b>%s</b></td><td>%s</td><td class="dim">%s</td></tr>' % tuple(r) for r in s4.get("slogans", []))
        title_rows = "".join('<tr><td>%s</td><td class="dim">%s</td></tr>' % tuple(r) for r in s4.get("title_samples", []))
        quote_rows = "".join('<tr><td><b>%s</b></td><td>%s</td><td class="dim">%s</td></tr>' % tuple(r) for r in s4.get("quotes", []))
        formula4 = "".join('<div class="fcell"><b>%s</b>%s</div>' % (c["t"], c["d"]) for c in s4.get("formula", []))
        checklist4 = "".join("<li>%s</li>" % i for i in s4.get("checklist", []))
        blk_stats = ('<div class="stats">' + stats4 + "</div>") if stats4 else ""
        blk_slogan = ("<h3>" + icon_for("标题句式") + " 4.2 固定口号系统</h3>"
                      "<table><tr><th>口号</th><th>出现场景</th><th>功能</th></tr>" + slogan_rows + "</table>") if slogan_rows else ""
        blk_title = ("<h3>" + icon_for("标题三段式") + " 4.3 标题三段式</h3><p>" + s4.get("title_formula", "")
                     + "</p><table><tr><th>样本</th><th>拆解</th></tr>" + title_rows + "</table>") if s4.get("title_formula") else ""
        blk_quote = ("<h3>" + icon_for("金句") + " 4.4 金句切片</h3>"
                     "<table><tr><th>话术线</th><th>示例（原文）</th><th>写作手法</th></tr>" + quote_rows + "</table>") if quote_rows else ""
        blk_ki = '<div class="ki">' + s4["ki"] + "</div>" if s4.get("ki") else ""
        blk_corpus = ("<h3>" + icon_for("语料口播") + " 4.5 口播语料地图</h3><p>" + s4["corpus"] + "</p>") if s4.get("corpus") else ""
        blk_formula = ('<h3>' + icon_for("带货产品") + ' 4.6 带货口播结构</h3><div class="formula">' + formula4 + "</div>") if formula4 else ""
        blk_cta = ("<h3>" + icon_for("CTA互动钩子") + " 4.7 CTA 与互动钩子</h3><p>" + s4["cta_note"]
                   + '</p><ul class="checklist">' + checklist4 + "</ul>") if s4.get("cta_note") else ""
        sec5 = f'''
<section id="s5"><h2>04 · 文案写作逻辑深度拆解</h2>
<div class="sec-sub">{s4.get("sub", "基于逐字稿与标题的全量拆解")}</div>
{s4.get("intro", "")}
{blk_stats}{blk_slogan}{blk_title}{blk_quote}{blk_ki}{blk_corpus}{blk_formula}{blk_cta}
</section>'''

    sec8 = ""
    if nar.get("s7"):
        s7n = nar["s7"]
        steps7 = "".join('<div class="step"><div><h5>%s</h5><p>%s</p></div></div>' % (s["t"], s["d"]) for s in s7n.get("steps", []))
        blk_steps7 = ('<h3>' + icon_for("产品带货") + ' 7.1 产品叙事模板</h3><div class="steps">' + steps7 + "</div>") if steps7 else ""
        blk_caveat7 = '<div class="note"><b>数据口径：</b>' + s7n["caveat"] + "</div>" if s7n.get("caveat") else ""
        sec8 = f'''
<section id="s8"><h2>07 · 带货与变现逻辑</h2>
<div class="sec-sub">{s7n.get("sub", "产品叙事模板 + 引流闭环")}</div>
{blk_steps7}
{s7n.get("note", "")}
{blk_caveat7}
</section>'''

    sec9 = ""
    if nar.get("s8"):
        s8n = nar["s8"]
        weak = "".join("<li>%s</li>" % w for w in s8n.get("weakness", []))
        plan = "".join(('<h3>' + icon_for(p["h"]) + " %s</h3><p>%s</p>") % (p["h"], p["p"]) for p in s8n.get("plan", []))
        comp = "".join("<li>%s</li>" % c for c in s8n.get("compliance", []))
        blk_weak = ("<h3>" + icon_for("弱点风险") + ' 对标弱点（数据实证）</h3><ul class="checklist">' + weak + "</ul>") if weak else ""
        blk_comp = ("<h3>" + icon_for("合规红线") + ' 合规层：话术红线（最高优先级）</h3><ul class="checklist">' + comp + "</ul>") if comp else ""
        sec9 = f'''
<section id="s9"><h2>08 · 差异化起号方案</h2>
<div class="sec-sub">对标账号的结构性弱点 = 你的切入点</div>
{blk_weak}
{plan}
{blk_comp}
</section>'''

    nav_secs = [("s0", "数据构成"), ("s1", "核心结论"), ("s2", "对标方法"), ("s3", "达人画像"), ("s4", "内容矩阵")]
    if sec5:
        nav_secs.append(("s5", "文案拆解"))
    if sec6:
        nav_secs.append(("s6", "评论区实证"))
    if sec7:
        nav_secs.append(("s7", "BGM×互动"))
    if sec8:
        nav_secs.append(("s8", "变现逻辑"))
    if sec9:
        nav_secs.append(("s9", "起号方案"))
    nav = "".join('<a href="#%s">%s</a>' % (i, t) for i, t in nav_secs)

    limit_lines = ["数据来源：MediaCrawler 全量抓取（%d 作品%s，%s）；采集工具 douyin-crawl-report 技能管线。"
                   % (n, (" + %s 评论" % f"{sum(v['n'] for v in comments['by_aweme'].values()):,}") if comments else "",
                      datetime.now().strftime("%Y-%m-%d"))]
    if missing:
        limit_lines.append("缺源声明：" + "、".join(missing) + "——相关章节已省略或标注，不虚构。")
    if nar.get("footer_extra"):
        limit_lines.append(str(nar["footer_extra"]))
    limit_lines.append("合规边界：仅供内部对标研究；引用的达人话术与用户评论不构成投放建议，商用前须过合规审查。")

    kicker = args.kicker or "Douyin Creator Benchmark · %s" % datetime.now().strftime("%Y.%m")
    title = args.title or "抖音达人对标分析报告"
    subtitle = args.subtitle or "账号拆解与差异化起号方案"
    html_doc = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title><style>{CSS}</style></head>
<body><div class="page">
<header class="masthead">
  <div class="kicker">{kicker}</div>
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="meta-line">{"".join(meta_items)}</div>
</header>
<nav><div class="nav-in">{nav}</div></nav>

<section id="s0">
  <div class="intro"><p>{intro}</p>
  <div class="pill-box"><h4>{icon('tag', 13)} 数据口径</h4>{"".join('<span class="pill">%s</span>' % p for p in pills)}</div></div>
  <div class="samples">{"".join(samples)}</div>
</section>

<section id="s1"><h2>核心结论</h2><div class="sec-sub">先看这里</div>
<div class="stats">{stats1}</div>{concl_html}</section>

<section id="s2"><h2>01 · 如何把达人列为对标账号</h2>
<div class="sec-sub">对标不是"看视频学说话"，是系统化采集-拆解-追踪流程</div>
<h3>{icon('chart')} 1.2 建立对标的五步法</h3>
<div class="steps">{steps2}</div>
{('<div class="note"><b>完成度：</b>' + nar["s2_note"] + "</div>") if nar.get("s2_note") else ""}
</section>

<section id="s3"><h2>02 · 达人画像总览</h2>
<div class="sec-sub">用全量数据回答：她是谁、粉丝盘多大、什么时候发</div>
<h3>{icon('chart')} 2.1 账号基本盘</h3>
<table><tr><th>维度</th><th>数据</th><th>解读</th></tr>{profile_rows}</table>
<h3>{icon('chat')} 2.2 互动特征：收藏率 vs 评论率</h3>
<p>藏/赞 {rate_col:.1f}% vs 评/赞 {rate_c:.1f}%。{nar.get("s3_interact", "")}</p>
{('<div class="note"><b>数据口径提示：</b>' + nar["s3_caveat"] + "</div>") if nar.get("s3_caveat") else ""}
<h3>{icon('clock')} 2.3 发布规律</h3>
<div class="chart-card"><h4>图 1 · 发布时段分布（按小时，{n} 条全量）</h4>
<div class="src">数据来源：video-analysis/{acc}/manifest.json</div>
<svg viewBox="0 0 620 130" width="100%" role="img">{hour_svg}</svg></div>
<p>{s3_auto}</p>
{('<div class="ki">' + nar["s3_ki"] + "</div>") if nar.get("s3_ki") else ""}
</section>

<section id="s4"><h2>03 · 内容矩阵拆解</h2>
<div class="sec-sub">内容不是"什么都发"，而是清晰的主次结构</div>
<h3>{icon('chart')} 3.1 内容主题结构</h3>
<table><tr><th>内容主题</th><th>条数</th><th>占比</th><th>平均赞</th><th>平均评</th><th>平均藏</th><th>定位</th></tr>{theme_rows}</table>
{('<div class="note"><b>口径说明：</b>' + nar["s4_note"] + "</div>") if nar.get("s4_note") else ""}
{('<h3>' + icon_for("爆款公式") + ' 3.2 爆款公式</h3><div class="formula">' + formula_html + "</div>") if formula_html else ""}
<h3>{icon('fire')} 3.3 爆款 TOP{args.top_n}（真实封面）</h3>
<table><tr><th></th><th>点赞</th><th>收藏</th><th>评论</th><th>分享</th><th>日期</th><th>标题</th></tr>{top_rows}</table>
{('<div class="ki">' + nar["s4_ki"] + "</div>") if nar.get("s4_ki") else ""}
{('<h3>' + icon_for("关键帧画面") + ' 3.4 爆款关键帧切片</h3><div class="fgallery">' + frame_cards + "</div>") if frame_cards else ""}
</section>

{sec5}{sec6}{sec7}{sec8}{sec9}

<footer>{"".join("<br>" + l if i else l for i, l in enumerate(limit_lines))}</footer>
</div></body></html>'''
    n_cov = sum(1 for m in top[:args.top_n] if cover(m["aweme_id"]))
    return html_doc, dict(n=n, covers=n_cov, frames=frame_cards.count("<figure"), missing=missing)

def selfcheck(page):
    """结构自检：标签平衡 + 导航锚点均有对应 section。返回问题列表（空=通过）。"""
    import re as _re
    bad = []
    for t in ("div", "section", "table", "svg", "figure", "ul", "ol", "li", "tr", "h2", "h3", "p", "span"):
        o = len(_re.findall(r"<%s[ >]" % t, page))
        z = page.count("</%s>" % t)
        if o != z:
            bad.append("<%s> %d/%d" % (t, o, z))
    anchors = set(_re.findall(r'href="#(s\d)"', page))
    ids = set(_re.findall(r'<section id="(s\d)"', page))
    for a in sorted(anchors - ids):
        bad.append("锚点 #%s 无对应 section" % a)
    return bad

def main():
    ap = argparse.ArgumentParser("report_html")
    ap.add_argument("--root", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--subtitle")
    ap.add_argument("--kicker")
    ap.add_argument("--narrative", help="定性槽位 JSON（intro/conclusions/s4/s6_ki/… 见 references/report-template.md）")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--frames-n", type=int, default=6)
    ap.add_argument("--img-cap-kb", type=int, default=400)
    a = ap.parse_args()
    page, stat = build(a)
    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(page)
    print("[report_html] %s (%d KB) | 作品 %d | TOP封面 %d/%d | 关键帧 %d | 缺源 %s"
          % (a.out, os.path.getsize(a.out) // 1024, stat["n"], stat["covers"], a.top_n,
             stat["frames"], "、".join(stat["missing"]) or "无"))
    bad = selfcheck(page)
    if bad:
        raise SystemExit("[report_html] 结构自检失败：%s" % "; ".join(bad))
    print("[report_html] 结构自检通过（标签平衡 + 锚点齐全）")

if __name__ == "__main__":
    main()
