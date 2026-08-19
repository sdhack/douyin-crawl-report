---
name: douyin-crawl-report
description: 从抖音账号/视频 URL 抓取视频数据（单个+批量），经数据处理、视觉/BGM/话术分析后生成对标分析报告。Invoke when user wants to crawl a Douyin creator's videos by account URL and produce an analysis report.
---

# 抖音账号抓取与报告生成

## 触发场景

- 提供**账号主页 URL**（`douyin.com/user/{sec_uid}`）→ 批量抓取全部视频
- 提供**单个视频 URL**（`douyin.com/video/{aweme_id}`）→ 抓取单条
- 要求基于已抓取数据生成**对标分析报告**

## 流程概览（4 阶段）

1. **抓取**（`tools/crawl.py`，技能内建 MediaCrawler 封装）：detail 模式抓单个，creator 模式批量抓账号。creator 的 `--max N` 由技能给 MediaCrawler 注入并验证硬上限，在保存回调前裁剪当前页，达到 N 后停止翻页；补丁不兼容时直接退出，后处理再按主页返回顺序硬截断一次，不能仅信任失效的 `--crawler_max_notes_count`。自动解析 MediaCrawler、断点续传、进度日志并隔离运行目录。**每个 creator 必须使用唯一 `--account` slug**；同一 slug 指向不同账号时直接拒绝。MediaCrawler 失败时不切其他抓取兜底。
   - **评论抓取**：默认开启，每个视频目标抓取 100 条一级评论（`--comments-count 100`）；只有显式传 `--no-comment` 才跳过。评论产物落 `<root>/crawl_<account>/douyin/jsonl/detail_comments_*.jsonl`，再由 `comments.py` 按赞聚合且每视频最多保留 100 条。评论 API 需登录态；登录态不可用或无法保证 100 条配置时直接失败，不静默降级。**注意**：批处理循环用 Python `subprocess` 驱动，勿用 `powershell -File` 拼中文路径。
2. **数据处理**：`process.py` 去重→manifest → `download.py` 下载视频/封面 → 图文切分。
3. **内容分析**：优先用 `analyze.py` 一键执行“音频转写 → 自适应抽帧与 BGM 并行 → 逐帧视觉分析”。每视频最低 12 个均匀采样点，前三秒 3 FPS，镜头突变补帧，低置信度视频 5 FPS；输出 `frames.json`、单视频 `visual-summary.json` 和账号 `_visual-summary.json`，覆盖画风、色彩、构图、场景候选、字幕样式与产品露出候选。场景和产品候选必须保留置信度/待复核状态，禁止当成确定识别结果。
4. **报告生成（v2 固定骨架，数据与叙事分离）**：对标报告用技能内建 **`tools/report_html.py`** 直出固定骨架 HTML——10 区骨架、统计、多枚 SVG 图表（周发布分布/月度趋势/主题环形/点赞分布/BGM 对比/情绪分布）与封面/关键帧自动内联固化在工具里，**全部统计数字由工具从管线产物实时计算**（manifest/comments/_cross/frames/covers），AI 只按 `references/report-template.md` 的槽位 schema 撰写 `narrative.json`（定性结论/口号/金句/方案），**不手写统计数字**；缺源章节自动省略并写入附言缺源声明，禁止虚构。**设计美学完全由 AI 决定**——AI 在 narrative 的 `design` 键（或 CLI `--design`）给出整套配色/圆角/阴影/字体 token，缺键回落到高可读性基线，每次报告主动换一套避免雷同。`render_report.py` **仅用于博主全量视频总结 / decompose 长文**（自由 md + **骨架恒定、设计美学完全由 AI 决定**，`--design '<json>'` 传视觉 token），**不再渲染对标报告**（双路径已收口，防打架）。若用户要求视频级逆向拆解 / 账号级深度总结，按 `references/decompose-methodology.md` 补齐数据链（全量每条第11节标签 → `decompose/tags.json` → 爆款TOP+典型11节深拆），**并先跑 `tools/account_metrics.py` 自动聚合账号级维度（发布节奏 / 互动交叉聚类 / 话题策略+高赞评论 → `decompose/<account>/_metrics.json`，为博主总结必吃数据）**，再按 `references/blogger-summary-prompt.md` 的**博主全量视频总结提示词**对全部视频做账号级总结（定位/选题地图/Hook/内容结构/画面/用户需求/爆款对比/DNA/机会/最终输出），产出 Markdown 后经 `tools/render_report.py` 渲染为 HTML。
> **参考骨架权威结构（用户在要求"H1/H2/H3 严格按参考 HTML 生成"时必须遵守）**：参考文件 `https://share.traecontent.cn/artifact/69IZX28CO_67JP` 的章节骨架为 **01~07 七章**——01 如何把达人列为对标账号 / 02 达人画像总览 / 03 内容矩阵拆解 / 04 文案写作逻辑深度拆解 / 05 带货与变现逻辑 / **06 直播逻辑** / 07 差异化起号方案，外层再套 数据样本构成五源卡 → 关键指标 4 大数字 → 核心结论。**注意 `report_html.py` 默认章节是 01~08（含独立「评论区实证」「BGM×互动」两章、**无 06 直播**），与参考骨架不一致**；当用户要求严格按照参考 HTML 的结构时，用 `render_report.py` + 手工复刻 `_benchmark_src.md`（照 report-template.md 的 01~07 骨架），勿用 report_html.py。

详细命令见 `references/workflow.md`、`references/commands.md`；经验教训见 `references/lessons-learned.md`；报告固定模板见 `references/report-template.md`；逐视频逆向拆解见 `references/decompose-methodology.md`；**博主全量视频总结提示词（账号级）见 `references/blogger-summary-prompt.md`**。

发布或推送本技能前必须读取 `references/distribution.md` 的“发布前检查”：Commit 信息一律使用中文，每次提交必须同步更新 README；发布版本还需同步 `manifest.json` 与 README 版本徽章。

## 实战优化要点（2026-08 迭代沉淀）

### 提速（Speed）
- **抓取**：抓取异常/漏抓时**优先修 MediaCrawler 自身**（签名参数、分页参数、登录态），核验真实视频数，**不切浏览器兜底**（历史上曾用浏览器内 fetch 直连 API 临时救急，已弃用——其与 MediaCrawler 抓取栈脱节，易再踩坑且违背"修根因"原则）。
- **管线断点续传**：下载/抽帧/转写均按产出自动跳过已完成项，换新数据只处理增量（实测 162 条中仅重跑新增 105 条）。
- **BGM 音源直用抓取 JSON**：`transcribe_bgm.py` 从 `video-analysis/<account>/manifest.json` 的 `music_url`（抓取字段 `music_download_url`）下载到本次运行的 `bgm/<account>/audio/` 后分析，**不再从 MP4 分离音频**；缺失或下载/解码失败直接报错退出，不回退。
- **转写同模型复用**：口播与 BGM 统一用 faster-whisper **large-v3**，BGM 复用口播已缓存的同一模型，**免二次联网下载**。GPU 默认 float16，不支持的卡自动降级 `int8_float32`（实测 RTF 0.27–0.30，仍远快于 CPU int8 的 1.61，约 5.6×）。
- **音频直连转写**：口播转写直接读取抓取 JSON 的 `music_download_url` 并复用本地音频缓存，不从 MP4 分离；缺源直接失败。低置信度结果标记 `needs_visual_review`，再结合抽帧字幕核验，不把画面核验伪装成转写成功。
- **运行日志与续跑**：每次抓取在本次运行目录根生成追加式 `run.log` 和原子更新的 `run-state.json`，运行中每 60 秒写进度心跳；显式复用 `--run-dir` 时校验账号身份并从 MediaCrawler cursor 与各阶段完成标记续跑。
- **运行根唯一**：首次抓取在父目录创建一个时间戳运行根并写 `.douyin-crawl-run.json`；后续评论、重试或补抓必须复用该根。即使 Agent 误把已有运行根再次传给 `--root`，工具也会识别并复用，禁止在运行根内再生成 `<account>-时间戳/`。
- **跨 Agent 当前指针**：父目录保存 `.douyin-crawl-current-<account>.json`，且创建运行根时使用账号级目录锁。其他 Agent 即使只传父目录，也会复用指针指向的运行根；旧任务无指针时只扫描父目录一级并选最近有效根，绝不选嵌套目录。只有用户明确开始新一轮时传 `--new-run`；不得习惯性新建。
- **阶段并行**：下载（网络 I/O）与抽帧（CPU）可并行；BGM 转写等口播转写完成后跑，避免争抢 CPU。

### 提质（Quality）
- **核实真实视频数**：抓取完成后必须与主页显示的视频数核对，防止签名失效导致的静默漏抓（曾只抓到 57/162 条）。
- **数据完整性验证**：新抓数据需覆盖旧数据（按 aweme_id 比对），字段齐全、时间跨度合理才算完成。
- **报告基于全量数据**：报告硬编码数字（总赞/均赞/分类条数/爆款榜）必须与最新数据集一致，不得沿用旧样本。
- **转写成功率 100%**：口播转写出现 error 自动补转，报告前确认 0 失败。
- **补充分：把抓到的但骨架没有的内容收进合适章节**——生成后若发现管线产物里还有参考骨架未直接呈现的实证（用户声音光谱与高赞评论原声→并入 03 内容矩阵；BGM×互动组间倍数→并入 03 声音层；产地/场景话题均赞 vs 品牌词→并入 03/04），以 H3 小节约放、不破坏参考骨架、不新增一级章节；引用必须从原始产物（manifest/_metrics/_cross/评论）读数，并配口径声明（评论为"按赞采纳样、每视频≤100 条、非全量"，BGM 组间倍数为"相关非因果"，发布时段无小时字段为"选题侧推断"）。

### 修复 Bug
- **`a_bogus` 签名失效**（症状：API 返回截断数据、漏抓）：核对该账号抓取栈的签名参数（`browser_version`/`os_name`/`pc_libra_divert`/`from_user_page` 等）并**修复 MediaCrawler 源码后重抓**，不切浏览器兜底。
- **分页提前终止**（症状：`has_more=0` 但实际有更多数据）：请求参数缺 `from_user_page=1`、`show_live_replay_strategy=1`、`need_time_list=1` 等。修复：补全参数后逐页抓取。
- **风控拦截（account blocked）**：签名参数（`browser_version`、`os_name`）与真实浏览器不一致。修复：从浏览器实时读取 `navigator` 信息动态生成参数，并加 `pc_libra_divert`。
- **CDP 误关浏览器**：`browser.close()` 在 `connect_over_cdp` 模式下会关闭用户正在用的 Chrome。修复：脚本结束只断开连接，不调用 `browser.close()`。
- **浏览器被锁定**：TRAE 浏览器控制插件可能锁定 CDP 浏览器，抓取前确认浏览器可用。

## 关键约束

- 单会话 ~230 条 API 限制，批量需断点续传分多次跑
- 请求间隔 8–10s，防 ArgusSecurityPlugin 拦截
- 视觉分析必须真实，不得用推断冒充
- 直播话术需人工校对口音误识别（产品名/工艺/专业术语）
- 报告图片用真实抽帧，不用 AI 生成图

### 报告呈现三大约束（硬性，2026-08-19 确立）
针对**博主全量视频总结 / decompose 长文**（`render_report.py`）：
1. **不要目录**：默认单栏无目录（顶部品牌横幅替代侧栏 nav），`--no-toc` 已为缺省；仅 `--toc` 显式恢复侧栏目录。
2. **图片不能太大太突兀**：渲染器默认把内联抽帧排版成「相册网格」——`figure.img` 两两成排（`width:calc(50% - 8px)`）、单图居中 ≤420px、`img` 限高 460px + 细边框 + 微内边距做成精致照片贴片，杜绝单张撑满整行。
3. **骨架全局固定**：以固定模板为准（`https://share.traecontent.cn/artifact/69IZX28CO_67JP`），**只换设计美学**（`--design '<json>'` 整套配色/字体/圆角/阴影 token），**绝不改动章节目录 / 大数字卡 / 收治区 callout 等 HTML 骨架结构**。

## 运行库与依赖策略（重要）

- **运行库安装在项目目录**：分析运行库统一落在各项目 `<项目根>/.runtime/py`（faster-whisper/av/pillow/numpy/cublas 等 27 项），**不装 C 盘**。
- **全局注册复用（换目录不重装）**：运行库路径写入全局指针 `~/.trae-cn/runtime-registry.json`，任何项目/目录调用都通过技能自带解析器 `tools/runtime.py` 复用同一套运行库：
  - `py -3 <skill>/tools/runtime.py py`（打印运行库解释器路径）
  - `py -3 <skill>/tools/runtime.py doctor`（校验依赖 + CUDA 探测）
  - `py -3 <skill>/tools/runtime.py run --tool <name>.py --root <工作根> --account <slug> [args]`（用运行库解释器跑工具）
  - 解析优先级：`DOUYIN_RUNTIME_PY` 环境变量 > 全局指针 > 项目 `.runtime/py`（仅此三档，技能旧 `.venv` 已弃用不参与解析）。
- **抓取引擎** MediaCrawler venv 同样在全局指针登记（`keys.mediacrawler`）；其源码暂存于 `~/.cache/codex-mediacrawler/`。
- **产物一律落项目目录**：视频→`videos/`、抽帧→`video-analysis/<账号>/frames`、转写→`transcript/`、模型缓存→项目 `models_cache/`（`HF_ENDPOINT`/`HF_HUB_DISABLE_XET=1` 已配置）。

## 内建一键流水线（tools/）

本技能自带 `tools/` 可执行脚本，从"**抓取 → 去重 → 下载 → 抽帧 → 口播转写 → 报告**"一条命令链跑通，统一输入 `--root <工作根> --account <账号slug>`，统一经 `tools/runtime.py run --tool` 走项目运行库解释器：
`crawl.py`（抓取）、`process.py`（去重清单）、`download.py`（下载）、`transcribe.py`（音频转写）、`extract_frames.py`（自适应抽帧）、`analyze_frames.py`（逐帧指标/OCR）、`transcribe_bgm.py`（BGM）、`bgm_cross.py`（BGM×互动）、`comments.py`（评论）、`decompose_prep.py`（视频档案）、`account_metrics.py`（账号聚合）、`report_html.py`（固定骨架报告）、`render_report.py`（自由 Markdown 报告）。各脚本按产物断点续传，完整用法见 `references/workflow.md` 与 `references/commands.md`。

## 输出契约

| 阶段 | 产物 | 路径 |
|---|---|---|
| 抓取 | JSONL（原始 + 过滤去重）+ 日志 | `crawl_<account>/`、`crawl_<account>/<account>_dedup.jsonl` |
| 处理 | 下载清单（互动排序） | `video-analysis/<account>/manifest.json` |
| 下载 | 视频 / 封面 | `videos/<account>/`、`covers/<account>/` |
| 分析 | 抽帧 + 口播转写 | `video-analysis/<account>/frames/<aweme_id>/`、`transcript/<account>/` |
| BGM | 归档 + 交叉统计 | `bgm/<account>/`（`_manifest.json`）、`bgm/<account>/_cross.json` |
| 报告 | 对标 HTML（v2 固定骨架，自包含单文件） | `{账号}-对标分析报告.html`（report_html.py）+ `video-analysis/<account>/narrative.json` |
| 报告 | 参考骨架版对标 HTML（01~07 含 06 直播，严格按参考 HTML） | `{账号}-对标分析报告（参考骨架）.html`（render_report.py + 手工 `_benchmark_src.md`） |
| 报告 | 博主总结 HTML（自由 md 渲染） | `{账号}-博主全量视频总结.html`（render_report.py） |
| 评论 | 聚合(每视频按赞截断) | `video-analysis/<account>/comments.json` |
| 拆解 | 全量档案 + 账号级聚合 | `decompose/<account>/video_profiles.{json,md}`、`decompose/<account>/_metrics.json` |

## Output Quality Guardrails

- Repair generic headings, cluttered notes, fragile visual assumptions, weak tables, and missing verification cues before handing work back.
- Map role, task, and format into skill behavior rather than copying a large prompt template into `SKILL.md`.
- Let the artifact's content choose the visual system; do not copy a fixed palette or report style from another skill without a clear reason.
- If output-specific evidence is missing, state the gap instead of inventing screenshots, citations, data, or examples.

## Honest Boundaries

- Use this skill for the recurring job described in the trigger, not for one-off adjacent requests.
- Treat missing inputs, unclear outputs, or conflicting constraints as reasons to ask one focused clarification.
- Do not add new references, scripts, evals, or governance unless they improve reliability more than they add weight.
- 遵守平台规则与法律边界：仅抓取公开信息，不做平台逆向、不做大规模爬虫。
