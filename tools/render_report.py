# -*- coding: utf-8 -*-
"""对标分析报告 · 通用 md → 干净卡片式自包含 HTML 渲染器（技能内建）。

骨架固定（对齐 references/report-template.md），但【视觉主题每次随机轮换】：
- `# 主标题`（首个）→ 页面大标题；章内独立 `# <数字…>` → 居中大数字卡；
  章内 `# <其它>`（口号/关键统计）→ 醒目大行卡。
- `## N *单位* …`（以数字+单位开头）→ 数据样本大数字卡（不进目录）；
  否则 `## ` → 一级章节 section（侧栏目录只收这一级，避免目录刷屏）。
- `### / ####` → 二级 / 三级标题，目录里默认折叠。
- `> ` → 收治区 callout，按「关键启示/关键洞察/数据口径提示/为什么…/可照抄的动作清单」五关键词自动配不同色。
- `|` 表格、``` 代码、![..](..) 真实抽帧图（`--inline` 可内联 base64 保持单文件）。

内容骨架恒定不变；每次渲染自动从 THEMES 主题库随机挑一套配色+组件风格，保证视觉不重样。
可用 --theme 指定、--theme-seed 复现。默认每次随机。

统一经运行库执行：py -3 <skill>/tools/runtime.py run --tool render_report.py --source <report.md> [--out x.html] [--inline] [--theme name] [--theme-seed N] [--no-toc]

用法：
  python tools/render_report.py --source 对标分析报告.md
  python tools/render_report.py --stdin --out 报告.html            # 直接用内容出 html 不落 md
  python tools/render_report.py --source 报告.md --theme slate      # 指定主题
  python tools/render_report.py --source 报告.md --theme-seed 7    # 固定种子复现某套
"""
import argparse, base64, html, os, random, re, sys

def esc(s):
    return html.escape(s, quote=False)

CALL = {
    "可照抄的动作清单": "todo",
    "数据口径提示": "caveat",
    "关键启示": "take",
    "关键洞察": "take",
    "为什么": "why",
}

def inline(s):
    s = esc(s)
    s = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), s)
    s = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<strong>%s</strong>" % m.group(1), s)
    # 单星斜体（须在双星粗体之后，且避开两侧同为 * 的成对标记）：*赞* / *中位* 等不再原样泄漏
    s = re.sub(r"(?<!\*)\*([^*\s][^*\n]*?)\*(?!\*)", lambda m: "<em>%s</em>" % m.group(1), s)
    s = re.sub(r"(?<!\w)#(\d{1,3})(?!\d)", lambda m: '<span class="ref">#%s</span>' % m.group(1), s)
    return s

def slug(s):
    s = re.split(r"[（(]", s)[0]
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff-]", "", s)
    return s[:42]

def is_h1_stat(t):
    body = t.lstrip("# ").strip()
    return bool(re.match(r"^[\d.,]", body))

def is_chapter_num(body):
    return bool(re.match(r"^0?\d{1,2}\s*[.．、]?\s*[\u4e00-\u9fff]", body))

def is_datacard(body):
    if re.search(r"\*[^*\s\r\n]+\*", body):
        return True
    return bool(re.match(r"^[\d.,]+\s*\*?(条|份|帧|首|时|小时|分钟|个|件|场|瓶|kg|克|毫升|h|%|人)", body))

def split_num_desc(body):
    m = re.match(r"^([\d.,]+%?\s*[*]?\s*\S*?)(?:\s+|$)", body, re.S)
    num = re.sub(r"\s*\*+\s*", "", body[:m.end(1)]) if m else body
    num = num.strip()
    desc = (body[m.end(1):] if m else "").strip()
    if not desc and num:
        desc = num
        num = ""
    return num, desc


class Parser:
    def __init__(self, src_dir, inline_media, flat=False):
        self.dir = src_dir
        self.inline = inline_media
        self.flat = flat
        self.out = []
        self.toc = []
        self.sec_cur = None
        self.img_cache = {}

    def img(self, path):
        if self.inline:
            p = os.path.join(self.dir, path)
            if not os.path.exists(p):
                return '<div class="img miss"><span>缺图</span><code>%s</code></div>' % esc(path)
            if p not in self.img_cache:
                self.img_cache[p] = base64.b64encode(open(p, "rb").read()).decode()
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
            return '<figure class="img"><img src="data:image/%s;base64,%s" alt="%s"></figure>' % (
                "jpeg" if ext in ("jpg", "jpeg") else ext, self.img_cache[p], esc(path))
        return '<figure class="img"><img src="%s" alt="%s" loading="lazy"></figure>' % (esc(path), esc(path))

    def h1(self, t, is_first):
        body = t.lstrip("#").strip()
        if is_first:
            self.out.append('<h1 class="doc-title">%s</h1>' % inline(body))
            return
        if is_h1_stat(t):
            num, desc = split_num_desc(body)
            self.out.append('<div class="bigstat"><span class="bs-num">%s</span><span class="bs-desc">%s</span></div>'
                            % (esc(num), inline(desc)))
        else:
            self.out.append('<div class="bigline">%s</div>' % inline(body))

    def h2(self, t):
        body = t.lstrip("## ").strip()
        if is_datacard(body) and not is_chapter_num(body):
            num, desc = split_num_desc(body)
            self.out.append('<div class="datacard"><div class="dcnum">%s</div><div class="dctext">%s</div></div>'
                            % (esc(num), inline(desc)))
            return
        sid = slug(body)
        self.toc.append((1, body, sid))
        if self.flat:
            self.out.append('<h2 class="c">%s</h2>' % inline(body))
            return
        if self.sec_cur is not None:
            self.out.append('</section>')   # 关闭上一个章节，避免 `<section>` 无限嵌套
        self.out.append('<section id="%s" class="sec"><h2>%s</h2>' % (sid, inline(body)))
        self.sec_cur = sid

    def h3(self, t):
        self.out.append('<h3>%s</h3>' % inline(t.lstrip("### ").strip()))

    def h4(self, t):
        self.out.append('<h4>%s</h4>' % inline(t.lstrip("#### ").strip()))

    def para(self, text):
        s = text.strip()
        if s == "由 TraeWork 生成" or s.startswith("Douyin "):
            self.out.append('<p class="meta">%s</p>' % esc(s))
            return
        if s.startswith("*") and s.endswith("*") and len(s) > 2:
            self.out.append('<p class="emline">%s</p>' % inline(s[1:-1]))
            return
        self.out.append('<p>%s</p>' % inline(s))

    def callout(self, line):
        content = inline(line.lstrip(">").strip())
        kind = "gen"
        for k, v in CALL.items():
            if k in content[:22]:
                kind = v
                break
        self.out.append('<div class="callout %s">%s</div>' % (kind, content))

    def table(self, rows):
        head = [c.strip() for c in rows[0].split("|")] if rows else []
        th = "".join("<th>%s</th>" % inline(c) for c in head)
        bod = []
        for r in rows[1:]:
            cells = [c.strip() for c in r.split("|")]
            while len(cells) < len(head):
                cells.append("")
            bod.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in cells[:len(head)]) + "</tr>")
        self.out.append('<div class="tblwrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, "".join(bod)))

    def ul(self, items):
        """嵌套列表：items = [(indent, text), …]，按缩进递进生成 <ul> 层级（选题地图/内容支柱树）。"""
        def build(rows):
            buff = []
            i = 0
            while i < len(rows):
                indent, text = rows[i]
                buff.append("<li>%s" % inline(text))
                j = i + 1
                child = []
                while j < len(rows) and rows[j][0] > indent:
                    child.append(rows[j]); j += 1
                if child:
                    buff.append(build(child))
                buff.append("</li>")
                i = j
            return "<ul>" + "".join(buff) + "</ul>"
        self.out.append(build(items))

    def ol(self, items):
        self.out.append('<ol>' + "".join("<li>%s</li>" % inline(i) for i in items) + "</ol>")

    def code(self, buf):
        self.out.append("<pre><code>" + esc(buf) + "</code></pre>")

    def wimg(self, path):
        self.out.append(self.img(path))


# ---------------------------- 视觉主题库 ----------------------------
# 每次渲染默认随机挑一套；骨架(HTML 类名/结构)恒定，只轮换配色与组件风格。
THEMES = {
    "heathrow": dict(bg="#f6f4ef", card="#ffffff", line="#ebe5da", ink="#23272f", mut="#7a8291",
        acc="#e2622b", acc2="#1f6f78", grad="#f28b3f", brandA="#23272f", brandB="#34313a",
        codeBg="#eee8dc", preBg="#24272e", thBg="#f2ede3", hoverBg="#fcf9f2", warm="#fbf3e9",
        calInk="#5a4a35", ds="soft", ts="tint", hs="under"),
    "celadon": dict(bg="#f1f6f4", card="#ffffff", line="#dbe6e1", ink="#20302b", mut="#6f8160",
        acc="#1f7a62", acc2="#b0532a", grad="#3f9b7d", brandA="#143b33", brandB="#1e5447",
        codeBg="#e2ede8", preBg="#123029", thBg="#e7f0ec", hoverBg="#f6fbf9", warm="#e9f4ef",
        calInk="#3f5a52", ds="soft", ts="tint", hs="under"),
    "paper": dict(bg="#faf8f4", card="#fffdf9", line="#e7e0d3", ink="#26221c", mut="#83796a",
        acc="#9a5b20", acc2="#6d3b77", grad="#b97a32", brandA="#2e2920", brandB="#4a4235",
        codeBg="#efe7d8", preBg="#2a241c", thBg="#efe9dc", hoverBg="#fdfaf4", warm="#f4eede",
        calInk="#5c4c33", ds="outline", ts="tint", hs="band"),
    "slate": dict(bg="#eef2f7", card="#ffffff", line="#dde4ee", ink="#202c3c", mut="#6d7c8f",
        acc="#2f6bc4", acc2="#11857f", grad="#5b8fe0", brandA="#1c2940", brandB="#2a3d5e",
        codeBg="#e7edf5", preBg="#1c1f2c", thBg="#e3eaf3", hoverBg="#f7fafe", warm="#e9f0f8",
        calInk="#38455b", ds="fill", ts="solid", hs="leftbar"),
    "plum": dict(bg="#f6f1f6", card="#ffffff", line="#e5dce6", ink="#2c2030", mut="#8a7788",
        acc="#8a3f9e", acc2="#0e7a78", grad="#a858b8", brandA="#2a1530", brandB="#3f2148",
        codeBg="#ede2ef", preBg="#211226", thBg="#efe4f0", hoverBg="#fbf7fb", warm="#f3eaf4",
        calInk="#5a3a5e", ds="soft", ts="tint", hs="under"),
    "night": dict(bg="#16181c", card="#1f2228", line="#31363f", ink="#e9e6df", mut="#9aa0ac",
        acc="#d9a441", acc2="#4fb0a0", grad="#e7b854", brandA="#000000", brandB="#1a1c21",
        codeBg="#2b2f37", preBg="#0f1114", thBg="#262a31", hoverBg="#23262d", warm="#1f1a10",
        calInk="#cfc8b8", ds="fill", ts="solid", hs="leftbar"),
    "moss": dict(bg="#f2f4ec", card="#ffffff", line="#e0e4d3", ink="#24291d", mut="#757c68",
        acc="#5b8a2f", acc2="#a0502a", grad="#79a94e", brandA="#222a17", brandB="#343f23",
        codeBg="#e9ecd9", preBg="#202715", thBg="#eaeeda", hoverBg="#f9faf2", warm="#edf1df",
        calInk="#4a5a38", ds="soft", ts="tint", hs="band"),
    "rose": dict(bg="#f8f2f0", card="#ffffff", line="#e9d9d4", ink="#2b2220", mut="#8a7670",
        acc="#c05b4a", acc2="#4f7f93", grad="#d4816f", brandA="#271b18", brandB="#3f2924",
        codeBg="#f0e4e0", preBg="#241a17", thBg="#f1e4e0", hoverBg="#fdf8f6", warm="#f8ece7",
        calInk="#6b4a42", ds="soft", ts="tint", hs="under"),
}
THEME_NAMES = list(THEMES.keys())
THEME_LABEL = {
    "heathrow": "暖橘墨画", "celadon": "青瓷", "paper": "纸感素印", "slate": "雾兰",
    "plum": "绛紫", "night": "暗夜鎏金", "moss": "苔绿", "rose": "蔷薇沙"
}

def pick_theme(args):
    if args.theme:
        if args.theme not in THEMES:
            sys.stderr.write("未知主题：%s，可选：%s\n" % (args.theme, ", ".join(THEME_NAMES)))
            raise SystemExit(2)
        return args.theme
    if args.theme_seed is not None:
        return random.Random(args.theme_seed).choice(THEME_NAMES)
    return random.choice(THEME_NAMES)


def build_css(t):
    v = THEMES[t]
    label = THEME_LABEL.get(t, t)
    root = (":root{--ink:%s;--mut:%s;--acc:%s;--acc2:%s;--grad:%s;--bg:%s;--card:%s;--line:%s;"
            "--brandA:%s;--brandB:%s;--codeBg:%s;--preBg:%s;--thBg:%s;--hoverBg:%s;--warm:%s;--calInk:%s;"
            "--todo:#0f5b61;--caveat:#7a3b1a;--why:#4b3a66;--take:#2f5233}" % (
        v["ink"], v["mut"], v["acc"], v["acc2"], v["grad"], v["bg"], v["card"], v["line"],
        v["brandA"], v["brandB"], v["codeBg"], v["preBg"], v["thBg"], v["hoverBg"],
        v["warm"], v["calInk"]))

    base = (
        "/* 对标分析报告 · 视觉主题: %s */\n" % label +
        "*{box-sizing:border-box;margin:0;padding:0}\n" + root + "\n"
        "html{scroll-behavior:smooth}\n"
        "body{font-family:'PingFang SC','Microsoft YaHei',-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.72;-webkit-font-smoothing:antialiased}\n"
        ".wrap{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:248px 1fr;gap:40px;padding:48px 34px}\n"
        "main{min-width:0}\n"
        ".rail{position:sticky;top:30px;align-self:start}\n"
        ".brand{background:linear-gradient(135deg,var(--brandA),var(--brandB));color:#fff;border-radius:16px;padding:20px;margin-bottom:16px}\n"
        ".brand-k{font-size:11px;letter-spacing:.18em;color:#e6a97f;font-weight:700}\n"
        ".brand-t{font-size:19px;font-weight:800;margin:7px 0 3px;line-height:1.25}\n"
        ".brand-s{font-size:12px;color:#c6c2bd}\n"
        ".toc{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;font-size:13px}\n"
        ".toc-t{font-weight:800;color:var(--acc);margin-bottom:8px;letter-spacing:.04em}\n"
        ".tc1{display:block;color:var(--ink);text-decoration:none;padding:4px 0 4px 9px;border-left:2px solid var(--line);margin-bottom:1px;font-weight:600}\n"
        ".tc1:hover{color:var(--acc);border-left-color:var(--acc)}\n"
        "details.tc2{display:block;margin:2px 0 4px 9px;border-left:2px solid var(--line);padding-left:8px}\n"
        "summary.t2{color:var(--mut);cursor:pointer;font-size:12.5px;padding:2px 0}\n"
        "summary.t2:hover{color:var(--acc)}\n"
        "h1.doc-title{font-size:30px;font-weight:900;color:var(--ink);padding-bottom:12px;margin-bottom:14px;line-height:1.3}\n"
        "p.meta{color:var(--mut);font-size:12.5px;letter-spacing:.03em;margin:2px 0}\n"
        "p.subtitle{color:var(--ink);font-size:18px;font-weight:700;margin:6px 0 18px}\n"
        "p.emline{color:var(--mut);font-style:italic;font-size:13.5px;margin:6px 0}\n"
        "h2{font-size:22px;font-weight:800;color:var(--ink);margin:0 0 16px;letter-spacing:.01em}\n"
        "h2.c{margin:34px 0 14px;padding-top:22px;border-top:2px solid var(--line)}\n"
        "h2.c:first-of-type{margin-top:0;padding-top:0;border-top:none}\n"
        "h3{font-size:16px;color:var(--acc2);margin:24px 0 8px;font-weight:800}\n"
        "h4{font-size:14px;color:var(--ink);margin:16px 0 6px;font-weight:800}\n"
        "p{margin:9px 0}\n"
        "strong{color:var(--acc);font-weight:700}\n"
        "code{background:var(--codeBg);padding:.8px 6px;border-radius:5px;font-size:.92em;color:var(--ink)}\n"
        ".ref{color:var(--acc);font-weight:700}\n"
        "pre{background:var(--preBg);color:#efe9de;padding:14px 16px;border-radius:12px;overflow:auto;font-size:12.5px;line-height:1.6;margin:12px 0}\n"
        "ul,ol{margin:6px 0 10px 22px}\n"
        "li{margin:3px 0}\n"
        "section.sec{padding:24px 26px;background:var(--card);border:1px solid var(--line);border-radius:16px;margin-bottom:22px}\n"
        ".bigstat{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:baseline;background:linear-gradient(135deg,var(--acc),var(--grad));color:#fff;border-radius:12px;padding:12px 20px;margin:10px 0;line-height:1.3}\n"
        ".bs-num{font-size:34px;font-weight:900;letter-spacing:.01em;white-space:nowrap}\n"
        ".bs-desc{font-size:14px;color:#fff6ee;font-weight:600}\n"
        ".bigline{border:1px solid var(--line);background:var(--warm);border-left:4px solid var(--acc);border-radius:10px;padding:10px 16px;margin:10px 0;font-size:15px;font-weight:700;color:var(--calInk)}\n"
        ".bigline code{background:#fff}\n"
        ".datacard{display:grid;grid-template-columns:112px 1fr;gap:14px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin:9px 0}\n"
        ".dcnum{font-size:30px;font-weight:900;color:var(--acc);text-align:center;letter-spacing:.02em}\n"
        ".dctext{font-size:13.5px;color:var(--ink)}\n"
        ".callout{border-left:4px solid var(--acc);background:var(--warm);border-radius:0 12px 12px 0;padding:12px 16px;margin:12px 0;color:var(--calInk)}\n"
        ".callout strong{color:var(--acc)}\n"
        ".callout.todo{border-color:var(--todo);background:#eef5f4;color:#33524f}\n"
        ".callout.caveat{border-color:var(--caveat);background:#fdf4e6;color:#6b4a1e}\n"
        ".callout.why{border-color:var(--why);background:#f3eefb;color:#4b3a66}\n"
        ".callout.take{border-color:var(--take);background:#eef6ef;color:#2f5233}\n"
        ".tblwrap{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:12px;background:var(--card)}\n"
        "table{border-collapse:collapse;width:max-content;min-width:520px;font-size:13px}\n"
        "th{background:var(--thBg);color:var(--ink);padding:9px 11px;text-align:left;font-weight:700;border-bottom:2px solid var(--line);white-space:nowrap}\n"
        "td{border-bottom:1px solid var(--line);padding:8px 11px;vertical-align:top}\n"
        "tbody tr:last-child td{border-bottom:none}\n"
        "tbody tr:hover td{background:var(--hoverBg)}\n"
        ".img{margin:12px 0}\n"
        ".img img{max-width:100%;border-radius:12px;border:1px solid var(--line);display:block}\n"
        ".img.miss{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px;color:var(--mut);font-size:13px}\n"
        ".wrap.single{grid-template-columns:1fr;max-width:900px}\n"
        ".wrap.single main{max-width:100%}\n"
        ".banner{background:linear-gradient(135deg,var(--brandA),var(--brandB));color:#fff;border-radius:16px;padding:26px 28px;margin-bottom:20px}\n"
        ".banner .brand-t{font-size:26px;font-weight:900;margin:6px 0 3px;line-height:1.25}\n"
        ".banner .brand-s{font-size:13px;color:#c6c2bd}\n"
        ".theme-note{text-align:right;color:var(--mut);font-size:11px;letter-spacing:.05em;margin-top:26px;padding-top:10px;border-top:1px dashed var(--line)}\n"
        "@media(max-width:900px){.wrap{grid-template-columns:1fr;padding:22px 16px}.rail{position:static}.datacard{grid-template-columns:1fr}}\n"
    )

    modes = []
    if v["ds"] == "fill":
        modes.append(".datacard{background:linear-gradient(135deg,var(--acc),var(--grad));border-color:transparent;color:#fff}")
        modes.append(".datacard .dcnum{color:#fff}")
        modes.append(".datacard .dctext{color:#fff6ee}")
    elif v["ds"] == "outline":
        modes.append(".datacard{border:2px solid var(--acc);box-shadow:none;background:var(--warm)}")
        modes.append(".datacard .dcnum{color:var(--acc)}")
    if v["ts"] == "solid":
        modes.append("th{background:linear-gradient(135deg,var(--brandA),var(--brandB));color:#fff;border-bottom:none}")
    elif v["ts"] == "line":
        modes.append("th{background:transparent;border-bottom:3px solid var(--acc);color:var(--acc)}")
    if v["hs"] == "leftbar":
        modes.append("h1.doc-title{border-left:6px solid var(--acc);padding-left:14px}")
    elif v["hs"] == "band":
        modes.append("h1.doc-title{background:linear-gradient(135deg,var(--brandA),var(--brandB));color:#fff;border-radius:12px;padding:14px 18px}")
    return base + "\n".join(modes) + "\n"


def render(text, src_dir, key, tagline, inline_media, title, no_toc=False, theme="heathrow"):
    p = Parser(src_dir, inline_media, flat=no_toc)
    lines = text.split("\n")
    in_code = False
    code_buf = []
    ul_buf = []
    ol_buf = []
    ul_open = ol_open = False
    first_h1 = True

    def flush_list():
        nonlocal ul_open, ol_open, ul_buf, ol_buf
        if ul_open and ul_buf:
            p.ul(ul_buf)
        if ol_open and ol_buf:
            p.ol(ol_buf)
        ul_buf, ol_buf = [], []
        ul_open = ol_open = False

    i = 0
    while i < len(lines):
        L = lines[i].rstrip()
        if L.startswith("```"):
            if in_code:
                p.code("\n".join(code_buf))
                code_buf, in_code = [], False
            else:
                flush_list(); in_code = True
        elif in_code:
            code_buf.append(L)
        elif L.startswith("# ") or L.startswith("## ") or L.startswith("### ") or L.startswith("#### "):
            flush_list()
            level = len(L) - len(L.lstrip("#"))
            body = L.lstrip("# ").strip()
            if not body:
                i += 1; continue
            if L.startswith("#### "):
                p.h4(L)
            elif L.startswith("### "):
                p.h3(L)
            elif L.startswith("## "):
                p.h2(L)
            else:
                p.h1(L, is_first=first_h1)
                first_h1 = False
        elif L.startswith(">"):
            flush_list()
            p.callout(L)
        elif re.match(r"^\s*\|", L):
            flush_list()
            rows = []
            while i < len(lines) and re.match(r"^\s*\|", lines[i]):
                t = lines[i].strip().strip("|")
                if t.strip():
                    rows.append(t)
                i += 1
            i -= 1
            if rows:
                p.table(rows)
        elif re.match(r"^!\[[^\]]*\]\([^)]+\)", L):
            flush_list()
            m = re.search(r"\]\(([^)]+)\)", L)
            if m:
                p.wimg(m.group(1).strip())
        elif re.match(r"^\s*[-*] ", L):
            if not ul_open:
                flush_list(); ul_open = True
            indent = len(L) - len(L.lstrip())
            ul_buf.append((indent, re.sub(r"^\s*[-*] ", "", L)))
        elif re.match(r"^\s*\d+\. ", L):
            if not ol_open:
                flush_list(); ol_open = True
            ol_buf.append(re.sub(r"^\s*\d+\. ", "", L))
        elif re.match(r"^\s*(?:---+|\*\*\*+)$", L):
            flush_list()
        elif L.strip() == "":
            flush_list()
        else:
            flush_list()
            if L.strip():
                p.para(L.strip())
        i += 1
    flush_list()
    if p.sec_cur is not None:
        p.out.append('</section>')   # 关闭最后一个章节，确保 body 中没有未闭合的 <section>

    body = "\n".join(p.out)

    if not title:
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else "对标分析报告"
    if not key:
        key = "DOUYIN BENCHMARK"
    if not tagline:
        m = re.search(r"^\*「([^*」]+)」(.+)\*$", text, re.M)
        tagline = ("「%s」%s" % (m.group(1), m.group(2)) if m else "账号拆解与差异化起号方案")

    note = '<div class="theme-note">视觉主题 · %s · 内容骨架恒定</div>' % esc(THEME_LABEL.get(theme, theme))

    toc_lines = []
    details_stack = []
    for lvl, t, sid in p.toc:
        if lvl == 1:
            while details_stack:
                toc_lines.append("</details>"); details_stack.pop()
            toc_lines.append('<a class="tc1" href="#%s">%s</a>' % (sid, inline(t)))
        else:
            if not details_stack:
                toc_lines.append('<details class="tc2"><summary class="t2">本节</summary>')
                details_stack.append(1)
            toc_lines.append('<a class="tc1 sub" href="#%s">%s</a>' % (sid, inline(t)))
    while details_stack:
        toc_lines.append("</details>"); details_stack.pop()

    if no_toc:
        rail = ('<div class="banner"><div class="brand-k">%s</div>'
                '<div class="brand-t">%s</div><div class="brand-s">%s</div></div>'
                % (key, esc(title), esc(tagline)))
        page = ("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>%s</title><style>%s</style></head>"
                "<body><div class=\"wrap single\">%s<main>%s%s</main></div></body></html>"
                % (esc(title), build_css(theme), rail, body, note))
        return page

    toc_html = ('<aside class="rail"><div class="brand"><div class="brand-k">%s</div>'
                '<div class="brand-t">%s</div><div class="brand-s">%s</div></div>'
                '<nav class="toc"><div class="toc-t">目录</div>%s</nav></aside>'
                % (key, esc(title), esc(tagline), "".join(toc_lines)))

    page = ("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>%s</style></head>"
            "<body><div class=\"wrap\">%s<main>%s%s</main></div></body></html>"
            % (esc(title), build_css(theme), toc_html, body, note))
    return page


def main():
    ap = argparse.ArgumentParser("render_report")
    ap.add_argument("--source", help="markdown 源文件（--source 与 --stdin 二选一）")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读 markdown 直接渲染 html，不落 .md 中间稿")
    ap.add_argument("--out")
    ap.add_argument("--title")
    ap.add_argument("--tagline")
    ap.add_argument("--key", default="DOUYIN BENCHMARK")
    ap.add_argument("--inline", action="store_true", help="封面/抽帧内联 base64，保持单文件")
    ap.add_argument("--no-toc", action="store_true", help="去掉侧栏目录，改单栏 + 顶部品牌横幅")
    ap.add_argument("--theme", help="指定视觉主题：%s（缺省每次随机）" % ", ".join(THEME_NAMES))
    ap.add_argument("--theme-seed", type=int, help="固定随机种子复现某套主题（用于回放/测试，缺省纯随机）")
    a = ap.parse_args()
    if not a.stdin and not a.source:
        ap.error("需要 --source <file.md> 或 --stdin（从标准输入渲染，直接出 html 不落 md）")

    theme = pick_theme(a)
    text = sys.stdin.read() if a.stdin else open(a.source, encoding="utf-8").read()
    src_dir = os.path.dirname(os.path.abspath(a.source)) if a.source else "."
    page = render(text, src_dir, a.key, a.tagline, a.inline, a.title, no_toc=a.no_toc, theme=theme)
    out = a.out or (os.path.splitext(a.source)[0] + ".html" if a.source else "report.html")
    open(out, "w", encoding="utf-8").write(page)
    print("渲染完成:", out, os.path.getsize(out), "bytes | 主题:", THEME_LABEL.get(theme, theme))


if __name__ == "__main__":
    main()