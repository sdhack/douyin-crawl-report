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

1. **抓取**（MediaCrawler）：detail 模式抓单个，creator 模式批量抓账号。断点续传 + 8–10s 间隔。**若发现漏抓，改用浏览器 fetch 直连 API 一次抓全**（见下方"修复 Bug"）。
2. **数据处理**：去重（`dedup_data.py`）→ 整合 → 下载视频/封面 → 图文切分。
3. **内容分析**：视频抽帧 → 真实视觉分析 → BGM 转写分类 → 直播话术校对口音误识别 → 各维度统计。
4. **报告生成**：`generate_per_video_report.py` → 逐视频报告；撰写对标分析报告（账号定位/内容矩阵/带货逻辑/素材拆解/起号方案）。**对标分析报告必须遵循 `references/report-template.md` 的固定模板结构输出**（文档头→引言→数据样本构成→关键指标→核心结论→01~07 章节→附言），只替换占位数据、不改骨架。

详细命令见 `references/workflow.md`、`references/commands.md`；经验教训见 `references/lessons-learned.md`；报告固定模板见 `references/report-template.md`。

## 实战优化要点（2026-08 迭代沉淀）

### 提速（Speed）
- **抓取**：execjs 签名失效时，用浏览器内 `fetch` 直连 `aweme/v1/web/aweme/post/` API（复用浏览器自身 `a_bogus`），一次抓全（实测 9 页 162 条），比逐条重试快一个数量级。
- **管线断点续传**：下载/抽帧/转写均按产出自动跳过已完成项，换新数据只处理增量（实测 162 条中仅重跑新增 105 条）。
- **转写多进程**：口播用 faster-whisper medium + 6 worker CPU 并行（162 条约 21 分钟）；BGM 用 small 模型（45 首约 4 分钟）。
- **阶段并行**：下载（网络 I/O）与抽帧（CPU）可并行；BGM 转写等口播转写完成后跑，避免争抢 CPU。

### 提质（Quality）
- **核实真实视频数**：抓取完成后必须与主页显示的视频数核对，防止签名失效导致的静默漏抓（曾只抓到 57/162 条）。
- **数据完整性验证**：新抓数据需覆盖旧数据（按 aweme_id 比对），字段齐全、时间跨度合理才算完成。
- **报告基于全量数据**：报告硬编码数字（总赞/均赞/分类条数/爆款榜）必须与最新数据集一致，不得沿用旧样本。
- **转写成功率 100%**：口播转写出现 error 自动补转，报告前确认 0 失败。

### 修复 Bug
- **`a_bogus` 签名失效**（症状：API 返回截断数据、漏抓）：execjs 生成的签名与真实浏览器环境不一致。修复：浏览器内 `fetch` 直连，复用浏览器签名。
- **分页提前终止**（症状：`has_more=0` 但实际有更多数据）：请求参数缺 `from_user_page=1`、`show_live_replay_strategy=1`、`need_time_list=1` 等。修复：补全参数后逐页抓取。
- **风控拦截（account blocked）**：签名参数（`browser_version`、`os_name`）与真实浏览器不一致。修复：从浏览器实时读取 `navigator` 信息动态生成参数，并加 `pc_libra_divert`。
- **CDP 误关浏览器**：`browser.close()` 在 `connect_over_cdp` 模式下会关闭用户正在用的 Chrome。修复：脚本结束只断开连接，不调用 `browser.close()`。
- **浏览器被锁定**：TRAE 浏览器控制插件可能锁定 CDP 浏览器，抓取前确认浏览器可用。

## 关键约束

- 单会话 ~230 条 API 限制，批量需断点续传分多次跑
- 请求间隔 8–10s，防 ArgusSecurityPlugin 拦截
- 视觉分析必须真实，不得用推断冒充
- 直播话术需人工校对口音误识别（产品名/工艺/茶底）
- 报告图片用真实抽帧，不用 AI 生成图

## 输出契约

| 阶段 | 产物 | 路径 |
|---|---|---|
| 抓取 | JSONL（去重后） | `data/douyin/jsonl/*_dedup.jsonl` |
| 处理 | 视频/封面/图文 | `videos/`、`data/douyin/sheets|cells/` |
| 分析 | 抽帧/视觉/BGM/话术 | `data/douyin/frames/`、`per_video_analysis.json` |
| 报告 | 逐视频 + 对标 | `per-video-breakdown.html`、`douyin-tea-benchmark.html` |

## Output Quality Guardrails

- Before final output, apply the likely failure modes in `reports/output-risk-profile.md` when that report is present.
- Before rendering reports, tutorials, review pages, dashboards, or visual artifacts, apply the artifact direction and visual quality gates in `reports/artifact-design-profile.md` when that report is present.
- When prompt behavior, role design, dialogue quality, or output contracts matter, apply `reports/prompt-quality-profile.md` when that report is present.
- Before adding more structure, apply the boundary, feedback-loop, drift, and leverage-point checks in `reports/system-model.md` when that report is present.
- Repair generic headings, cluttered notes, fragile visual assumptions, weak tables, and missing verification cues before handing work back.
- Map role, task, and format into skill behavior rather than copying a large prompt template into `SKILL.md`.
- Let the artifact's content choose the visual system; do not copy a fixed palette or report style from another skill without a clear reason.
- If output-specific evidence is missing, state the gap instead of inventing screenshots, citations, data, or examples.

## Honest Boundaries

- Use this skill for the recurring job described in the trigger, not for one-off adjacent requests.
- Treat missing inputs, unclear outputs, or conflicting constraints as reasons to ask one focused clarification.
- Do not add new references, scripts, evals, or governance unless they improve reliability more than they add weight.
- 遵守平台规则与法律边界：仅抓取公开信息，不做平台逆向、不做大规模爬虫。
