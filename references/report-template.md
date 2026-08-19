# 对标分析报告 · 固定输出模板 v2（MANDATORY）

> 固定骨架来源：`https://share.traecontent.cn/artifact/69IZX28CO_67JP`（抖音茶类达人对标分析报告，TraeWork 生成）；
> v2 视觉与骨架于 2026-08-19 固化（胶原蛋白肽类目账号首跑验证）。
> 状态：**本技能所有对标分析报告的标准输出结构，优先级最高**。

## v2 核心原则：数据与叙事分离

1. **全部数字由工具实时计算**——`tools/report_html.py` 直接读管线产物（manifest / comments / bgm _cross / frames / covers / transcript），报告中的作品数、互动均值、时段分布、主题条数、评论统计、BGM 组间均值一律程序生成，**AI 不得手写任何统计数字**（历史教训：手写数字与数据集漂移、旧项目抽帧混入新报告）。
2. **AI 只提供定性叙事**——经 `--narrative narrative.json` 注入（结论、口号、金句、方案等），槽位见下文 schema。
3. **缺源如实省略**——评论/BGM/关键帧/逐字稿任一源缺失时对应章节自动省略并在附言声明，禁止虚构。
4. **图片只用真实素材**——TOP 榜内联真实封面 `covers/<account>/<aweme_id>.jpg`；爆款区内联真实关键帧 `video-analysis/<account>/frames/<aweme_id>/`（取中位帧）；单图超 `--img-cap-kb`(默认 400KB) 自动跳过。禁止 AI 生成图、禁止引用账号目录之外的图片（防旧项目污染）。
5. **设计美学完全由 AI 决定（多图表优先）**——生成器不内置多套预设、不做随机轮换。视觉写成 CSS 变量 token，AI 在 narrative.json 的 `design` 键（dict）或 CLI `--design '<json>'` 里给出整套配色/圆角/阴影/字体；未给键自动回落到高可读性基线并自动按 `ink` 亮度推导反色文字，保证任何配色都可读。报告自动穿插多枚 SVG 图表与真图，务必在 narrative 撰写时让内容与图表相互印证。

## 固定骨架（10 区，恒定）

```
masthead(kicker+标题+副题+六源 meta) → sticky 导航
s0 数据构成（intro + 数据口径 pills + 五源样本卡）
s1 核心结论（4 自动大数字 + 5-6 条结论段落）
s2 01·如何对标（五步法 steps + 完成度 note）
s3 02·达人画像（基本盘表 + 互动特征 + 发布时段 SVG + 周发布分布 + 月度趋势×均赞 双图）
s4 03·内容矩阵（主题占比环形图 + 点赞分布图 + 主题表 + 爆款公式格 + TOP-N 真实封面表 + 爆款关键帧 + 各主题代表帧画廊）
s5 04·文案拆解（全 narrative：口号表/标题三段式/金句表/语料地图/带货结构/CTA）
s6 05·评论区实证（评论主题 hbar + 高赞 Top6 卡 + 摩擦原声分组）
s7 06·BGM×互动（BGM×互动对比图 + 组间表 + 情绪均赞分布 + 轻/纯口播倍数）
s8 07·变现逻辑（叙事 steps + 推断型 caveat）
s9 08·起号方案（弱点清单 + 分层方案 + 合规红线清单）
footer 诚实口径附言（数据来源/缺源声明/合规边界，自动）
```

图表全部由工具从管线产物实时计算（manifest/comments/_cross），骨架与数据契约不变；**视觉不锁定**——每次报告的配色/字体/圆角/阴影由 AI 在写 narrative 时自由指定，避免千篇一律，可读性由基线 + 反色文字推导兜底。

## 生成命令

```
py -3 <skill>/tools/runtime.py run --tool report_html.py -- \
    --root <工作根> --account <slug> \
    --title "抖音{品类}达人对标分析报告" \
    --subtitle "「{账号}」账号拆解与差异化起号方案" \
    --narrative <工作根>/video-analysis/<slug>/narrative.json \
    [--design '<json>'] \
    --out {账号}-对标分析报告.html
```

- `--design '<json>'` 可选：视觉 token dict，优先级高于 narrative.design（漏键回落基线）。
- `--frames-n`（默认 8）与 `--top-n`（默认 10）控制关键帧画廊与 TOP 表规模。

生成器**内置结构自检**（标签平衡 + 导航锚点齐全），失败即退出非零码；产物自包含单文件。

## narrative.json 槽位 schema（全部可选；缺省行为注明）

| 槽位 | 类型 | 缺省行为 |
|---|---|---|
| `design` | dict{token:value} | 回落到高可读性基线（配色/圆角/阴影/字体） |
| `intro` | str | 自动摘要（标注「自动摘要」） |
| `pills` | [str] | 自动（视频数/时间跨度/评论覆盖/非抽样） |
| `conclusions` | [str] | 4 条数据自动摘要（标注「自动摘要」） |
| `benchmark_steps` | [{t,d}] | 固定五步法默认文案 |
| `profile_rows` | [[维度,数据,解读]] | 追加在自动行之后 |
| `theme_rules` | [[标签,[关键词]]] | 内置默认规则（打假/测评/体验/科普） |
| `theme_roles` | {标签:定位语} | 空（定位列留白） |
| `formula` | [{t,d}] | 3.2 爆款公式区块省略 |
| `s3_interact` / `s3_caveat` / `s3_ki` | str | 对应句/块省略 |
| `s4_note` / `s4_ki` | str | 对应块省略 |
| `s4` | object | **整章 04 省略**（含 stats/slogans/title_formula/title_samples/quotes/ki/corpus/formula/cta_note/checklist） |
| `s6_note` / `s6_ki` | str | 口径用默认文本 / 洞察块省略 |
| `comment_patterns` | {主题:正则} | 内置通用电商评论模式 |
| `comment_groups` | {组名:[(赞,文本)]} | 自动按内置模式取样 |
| `s7_ki` | str | 洞察块省略 |
| `s7` | object | **整章 07 省略**（steps/note/caveat） |
| `s8` | object | **整章 08 省略**（weakness/plan[{h,p}]/compliance） |
| `footer_extra` | str | 不追加 |

写作规范沿用 v1：加粗首词结论、①②③ 序号、达人原话用「」、凡口径可能被筛选必须 `s3_caveat` 声明上界。

## design 视觉 token 参考（AI 在 narrative.json 的 `design` 键给出，缺键回落基线）

| token | 含义 | 建议建议范围示例 |
|---|---|---|
| `ink` | 正文主色 | 深中性色（越高自动推导反色文字） |
| `ink70` / `ink30` | 次级/弱化文字 | 由主色渐变的灰阶 |
| `paper` | 页面底色 | 米白/暖白/深底 |
| `card` | 卡片/导航底色 | 与 paper 区分 |
| `line` | 描边/分隔线 | 浅灰 |
| `rose` / `rose-bg` | 强调色（主调） | 一组对比色对 |
| `gold` / `gold-bg` | 次级强调（注意/口径） | 一组对比色对 |
| `c1`..`c4` | 图表明暗 / 分类色 | 互缺分明即可 |
| `serif` | 标题字体栈 | 中文衬线优先 |
| `sans` | 正文字体栈 | 系统无衬线 |
| `radius` | 卡片圆角 | 8–18px |
| `shadow` | 卡片阴影 | 柔和偏移阴影 |

每次撰写 narrative 时**主动换一套与账号品类气质匹配的配色/字体**，避免与上一份报告雷同；可读性由基线兜底，无需担心对比度。

## 与 render_report.py 的分工（防双路径打架）

- **对标分析报告** → 只走 `report_html.py`（固定骨架 + 数据驱动），**不再**经 render_report.py。
- **博主全量视频总结 / decompose 长文** → 仍走 `render_report.py`（自由 md + 主题轮换），输入为其专属提示词产出的 markdown。
- 两者产物互不替代；SKILL.md 第 4 阶段与 commands.md 已按此分工接线。

## 复用入口

1. 管线跑完（含 comments / bgm_cross / frames / covers）；
2. AI 按本 schema 撰写 `narrative.json`（定性内容与真实逐字稿/评论一致，数字留空由工具算）；
3. 跑生成命令 + 结构校验；
4. 交付 `{账号}-对标分析报告.html`（自包含单文件）。
