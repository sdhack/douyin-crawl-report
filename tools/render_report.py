# -*- coding: utf-8 -*-
"""博主全量视频总结 · 通用 md → 自包含 HTML 渲染器（技能内建）。

【骨架恒定，设计美学完全由 AI 决定】— 与 report_html.py 同一套设计令牌（design token）系统：
- 视觉令牌写成 CSS 变量，每次渲染由 AI 主动给出整套配色/圆角/阴影/字体（--design '<json>' 或脚本参数 design），
  未给的键自动回落到高可读性基线 NEUTRAL_DEFAULT；不内置多套预设、不做随机轮换（避免千篇一律、杜绝越随机越丑）。
- 结构映射恒定：
  `# 主标题`（首个）→ 页面大标题；章内独立 `# <数字…>` → 居中大数字卡；章内 `# <其它>` → 醒目大行卡。
  `## N *单位* …`（以数字+单位开头）→ 数据样本大数字卡（不进目录）；否则 `## ` → 一级章节（侧栏目录只收一级）。
  `> ` → 收治区 callout；`|` 表格、``` 代码、![..](..) 真实抽帧图（--inline 内联 base64 保持单文件）。

统一经运行库执行：py -3 <skill>/tools/runtime.py run --tool render_report.py --source <report.md> [--out x.html] [--inline] [--design '<json>'] [--toc]

用法：
  python tools/render_report.py --source 总结.md --inline --design '{"ink":"#23201b","acc":"#c05a2e","serif":"...","radius":"16px",...}'   # 无目录单栏（缺省）
  python tools/render_report.py --source 总结.md --toc                    # 有意恢复侧栏目录
  python tools/render_report.py --stdin --out 报告.html            # 直接用内容出 html 不落 md
"""
import argparse, base64, html, json, os, re, sys

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


# ---------------------------- 设计系统（骨架恒定，美学完全由 AI 决定） ----------------------------
# 视觉令牌写成 CSS 变量，AI 经 --design '<json>' 或脚本参数 design 给出整套配色/圆角/阴影/字体；
# 未给的键自动回落到高可读性基线 NEUTRAL_DEFAULT。不内置多套预设、不做随机轮换。
NEUTRAL_DEFAULT = dict(
    bg="#f6f3ee", card="#ffffff", line="#e8e1d3", ink="#252019", mut="#7d7465",
    acc="#c05a2e", acc2="#8a6b3f", grad="#e2884c", brandA="#3c2a18", brandB="#6b4526",
    codeBg="#efe8da", preBg="#2b2218", thBg="#f0e8da", hoverBg="#faf5ec", warm="#faebdd",
    calInk="#6b4a2c", serif='"Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif',
    sans='-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',
    radius="16px", radiusS="10px",
    shadow="0 10px 30px rgba(40,28,16,.07)",
)
ALLOWED = set(NEUTRAL_DEFAULT) | {"name", "on_ink", "on_ink_70"}

def _luminance(hexcolor):
    h = (hexcolor or "#20242b").lstrip("#")
    try:
        r, g, b = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return 0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def build_tokens(d):
    return (":root{--ink:%(ink)s;--mut:%(mut)s;--bg:%(bg)s;--card:%(card)s;--line:%(line)s;"
            "--acc:%(acc)s;--acc2:%(acc2)s;--grad:%(grad)s;--brandA:%(brandA)s;--brandB:%(brandB)s;"
            "--codeBg:%(codeBg)s;--preBg:%(preBg)s;--thBg:%(thBg)s;--hoverBg:%(hoverBg)s;--warm:%(warm)s;--calInk:%(calInk)s;"
            "--serif:%(serif)s;--sans:%(sans)s;--radius:%(radius)s;--radius-s:%(radiusS)s;--shadow:%(shadow)s;"
            "--on-ink:%(on_ink)s;--on-ink-70:%(on_ink_70)s;"
            "--todo:#0f5b61;--caveat:#8a5a1a;--why:#5a3d7a;--take:#2f5b33}") % d

def resolve_design(di=None, raw=None):
    """骨架恒定；视觉令牌完全由 AI 决定。优先级：--design '<json>' > di(dict) > 可读性基线。
    另按 ink 亮度自动推导深/浅底反色文字令牌（AI 可覆盖），保证可读性。"""
    base = dict(NEUTRAL_DEFAULT)
    spec = None
    if raw:
        try:
            spec = json.loads(raw)
        except Exception:
            sys.stderr.write("[render_report] 无法解析 --design 为 JSON，已忽略改用默认值。\n")
            spec = None
    if not spec and isinstance(di, dict):
        spec = di
    if isinstance(spec, dict):
        base.update({k: v for k, v in spec.items() if k in ALLOWED})
    dark = _luminance(base["ink"]) < 150
    base.setdefault("on_ink", "#ffffff" if dark else "#4a3a24")
    base.setdefault("on_ink_70", "#e6ddcf" if dark else "#6b5138")
    return base


def build_css(d):
    toks = build_tokens(d)
    css = (
        "/* 博主全量视频总结 · 设计美学由 AI 决定（骨架恒定） */\n"
        "*{box-sizing:border-box;margin:0;padding:0}\n"
        "html{scroll-behavior:smooth}\n"
        "body{font-family:var(--sans);background:var(--bg);color:var(--ink);line-height:1.75;-webkit-font-smoothing:antialiased;"
        "background-image:radial-gradient(1100px 480px at 88% -60px,var(--warm),transparent 62%),radial-gradient(800px 380px at -120px 0,var(--hoverBg),transparent 55%)}\n"
        ".wrap{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:248px 1fr;gap:40px;padding:52px 34px}\n"
        "main{min-width:0}\n"
        ".rail{position:sticky;top:30px;align-self:start}\n"
        ".brand{background:linear-gradient(152deg,var(--brandA),var(--brandB));color:#fff;border-radius:var(--radius);padding:22px;margin-bottom:16px;box-shadow:var(--shadow);position:relative;overflow:hidden}\n"
        ".brand::after{content:'';position:absolute;right:-34px;top:-34px;width:140px;height:140px;border-radius:50%;background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.14),transparent 70%)}\n"
        ".brand-k{font-size:11px;letter-spacing:.2em;color:var(--on-ink-70);font-weight:700;opacity:.9}\n"
        ".brand-t{font-size:20px;font-weight:900;margin:8px 0 4px;line-height:1.3;font-family:var(--serif)}\n"
        ".brand-s{font-size:12px;color:var(--on-ink-70)}\n"
        ".toc{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;font-size:13px;box-shadow:var(--shadow)}\n"
        ".toc-t{font-weight:800;color:var(--acc);margin-bottom:10px;letter-spacing:.08em;font-size:12px}\n"
        ".tc1{display:block;color:var(--ink);text-decoration:none;padding:5px 0 5px 11px;border-left:2px solid var(--line);margin-bottom:2px;font-weight:600;transition:all .15s}\n"
        ".tc1:hover{color:var(--acc);border-left-color:var(--acc);padding-left:15px}\n"
        "details.tc2{display:block;margin:2px 0 4px 11px;border-left:2px solid var(--line);padding-left:9px}\n"
        "summary.t2{color:var(--mut);cursor:pointer;font-size:12.5px;padding:2px 0}\n"
        "summary.t2:hover{color:var(--acc)}\n"
        "h1.doc-title{font-size:31px;font-weight:900;line-height:1.3;padding-bottom:14px;margin-bottom:16px;font-family:var(--serif);"
        "background:linear-gradient(90deg,var(--acc),var(--grad));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;"
        "border-bottom:3px solid var(--acc2)}\n"
        "p.meta{color:var(--mut);font-size:12.5px;letter-spacing:.04em;margin:2px 0}\n"
        "p.subtitle{color:var(--ink);font-size:18px;font-weight:700;margin:6px 0 18px}\n"
        "p.emline{color:var(--mut);font-style:italic;font-size:13.5px;margin:6px 0}\n"
        "h2{font-size:23px;font-weight:800;color:var(--ink);margin:0 0 16px;letter-spacing:.02em;font-family:var(--serif)}\n"
        "h2.c{margin:36px 0 16px;padding-top:24px;border-top:2px solid var(--line)}\n"
        "h2.c:first-of-type{margin-top:0;padding-top:0;border-top:none}\n"
        "h3{font-size:16.5px;color:var(--acc2);margin:26px 0 8px;font-weight:800;display:flex;align-items:center;gap:8px}\n"
        "h3::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--acc);flex:none}\n"
        "h4{font-size:14px;color:var(--ink);margin:18px 0 6px;font-weight:800}\n"
        "p{margin:10px 0}\n"
        "strong{color:var(--acc);font-weight:700}\n"
        "code{background:var(--codeBg);padding:2px 7px;border-radius:6px;font-size:.9em;color:var(--ink)}\n"
        ".ref{color:var(--acc);font-weight:700}\n"
        "pre{background:var(--preBg);color:#efe9de;padding:15px 17px;border-radius:12px;overflow:auto;font-size:12.5px;line-height:1.6;margin:12px 0;border:1px solid var(--line)}\n"
        "ul,ol{margin:6px 0 12px 24px}\n"
        "li{margin:4px 0}\n"
        "section.sec{padding:26px 30px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:24px;box-shadow:var(--shadow)}\n"
        ".bigstat{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:baseline;background:linear-gradient(135deg,var(--acc),var(--grad));color:#fff;border-radius:var(--radius-s);padding:14px 22px;margin:12px 0;line-height:1.3;box-shadow:0 8px 22px -12px var(--acc)}\n"
        ".bs-num{font-size:36px;font-weight:900;letter-spacing:.01em;white-space:nowrap;font-family:var(--serif)}\n"
        ".bs-desc{font-size:14px;color:var(--on-ink-70);font-weight:600}\n"
        ".bigline{border:1px solid var(--line);background:var(--warm);border-left:5px solid var(--acc);border-radius:var(--radius-s);padding:12px 18px;margin:12px 0;font-size:15px;font-weight:700;color:var(--calInk)}\n"
        ".bigline code{background:#fff}\n"
        ".datacard{display:grid;grid-template-columns:118px 1fr;gap:16px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:var(--radius-s);padding:16px 20px;margin:10px 0;transition:transform .15s,border-color .15s}\n"
        ".datacard:hover{transform:translateY(-2px);border-color:var(--acc2)}\n"
        ".dcnum{font-size:32px;font-weight:900;color:var(--acc);text-align:center;letter-spacing:.02em;font-family:var(--serif);position:relative}\n"
        ".dcnum::after{content:'';position:absolute;left:50%;bottom:-7px;width:34px;height:3px;border-radius:2px;background:linear-gradient(90deg,var(--acc),var(--grad));transform:translateX(-50%)}\n"
        ".dctext{font-size:13.5px;color:var(--ink)}\n"
        ".callout{border-left:5px solid var(--acc);background:var(--warm);border-radius:0 var(--radius-s) var(--radius-s) 0;padding:14px 18px;margin:14px 0;color:var(--calInk)}\n"
        ".callout strong{color:var(--acc)}\n"
        ".callout.todo{border-color:var(--todo);background:#eef5f4;color:#33524f}\n"
        ".callout.caveat{border-color:var(--caveat);background:#fdf4e6;color:#6b4a1e}\n"
        ".callout.why{border-color:var(--why);background:#f3eefb;color:#4b3a66}\n"
        ".callout.take{border-color:var(--take);background:#eef6ef;color:#2f5233}\n"
        ".tblwrap{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:var(--radius-s);background:var(--card);box-shadow:var(--shadow)}\n"
        "table{border-collapse:collapse;width:max-content;min-width:520px;font-size:13px}\n"
        "th{background:linear-gradient(135deg,var(--brandA),var(--brandB));color:#fff;padding:11px 13px;text-align:left;font-weight:700;border-bottom:none;white-space:nowrap;letter-spacing:.03em}\n"
        "td{border-bottom:1px solid var(--line);padding:9px 13px;vertical-align:top}\n"
        "tbody tr:last-child td{border-bottom:none}\n"
        "tbody tr:hover td{background:var(--hoverBg)}\n"
        "figure.img{display:inline-block;vertical-align:top;width:calc(50% - 8px);text-align:center;margin:0 0 18px}\n"
        "figure.img:nth-of-type(odd){margin-right:16px}\n"
        "figure.img:only-of-type{display:block;width:auto;max-width:420px;margin:0 auto 18px}\n"
        ".img img{max-width:100%;max-height:460px;width:auto;height:auto;border-radius:12px;border:1px solid var(--line);box-shadow:var(--shadow);background:var(--card);padding:4px}\n"
        ".img.miss{max-width:420px;margin:0 auto;background:var(--card);border:1px dashed var(--line);border-radius:var(--radius-s);padding:16px;color:var(--mut);font-size:13px;text-align:center}\n"
        ".wrap.single{grid-template-columns:1fr;max-width:920px}\n"
        ".wrap.single main{max-width:100%}\n"
        ".banner{background:linear-gradient(152deg,var(--brandA),var(--brandB));color:#fff;border-radius:var(--radius);padding:28px 30px;margin-bottom:24px;box-shadow:var(--shadow);position:relative;overflow:hidden}\n"
        ".banner::after{content:'';position:absolute;right:-40px;bottom:-64px;width:210px;height:210px;border-radius:50%;background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.12),transparent 70%)}\n"
        ".banner .brand-t{font-size:28px;font-weight:900;margin:6px 0 4px;line-height:1.25;font-family:var(--serif)}\n"
        ".banner .brand-s{font-size:13px;color:var(--on-ink-70)}\n"
        ".design-note{text-align:right;color:var(--mut);font-size:11px;letter-spacing:.06em;margin-top:28px;padding-top:12px;border-top:1px dashed var(--line)}\n"
        "@media(max-width:900px){.wrap{grid-template-columns:1fr;padding:22px 16px}.rail{position:static}.datacard{grid-template-columns:1fr}}\n"
    )
    return toks + "\n" + css


def render(text, src_dir, key, tagline, inline_media, title, no_toc=False, design=None):
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

    if design is None:
        design = resolve_design()

    note = '<div class="design-note">设计美学 · 由 AI 决定 · 内容骨架恒定</div>'

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
                % (esc(title), build_css(design), rail, body, note))
        return page

    toc_html = ('<aside class="rail"><div class="brand"><div class="brand-k">%s</div>'
                '<div class="brand-t">%s</div><div class="brand-s">%s</div></div>'
                '<nav class="toc"><div class="toc-t">目录</div>%s</nav></aside>'
                % (key, esc(title), esc(tagline), "".join(toc_lines)))

    page = ("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>%s</style></head>"
            "<body><div class=\"wrap\">%s<main>%s%s</main></div></body></html>"
            % (esc(title), build_css(design), toc_html, body, note))
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
    ap.add_argument("--toc", action="store_true", help="恢复侧栏目录（博主总结硬性要求默认单栏无目录；骨架仍恒定，--no-toc 已为缺省）")
    ap.add_argument("--design", help="视觉令牌 JSON dict（键见 NEUTRAL_DEFAULT，漏键自动回落可读性基线）；缺省用基线")
    a = ap.parse_args()
    if not a.stdin and not a.source:
        ap.error("需要 --source <file.md> 或 --stdin（从标准输入渲染，直接出 html 不落 md）")

    design = resolve_design(raw=a.design)
    text = sys.stdin.read() if a.stdin else open(a.source, encoding="utf-8").read()
    src_dir = os.path.dirname(os.path.abspath(a.source)) if a.source else "."
    page = render(text, src_dir, a.key, a.tagline, a.inline, a.title, no_toc=not a.toc, design=design)
    out = a.out or (os.path.splitext(a.source)[0] + ".html" if a.source else "report.html")
    open(out, "w", encoding="utf-8").write(page)
    print("渲染完成:", out, os.path.getsize(out), "bytes | 设计美学: AI 定制")


if __name__ == "__main__":
    main()