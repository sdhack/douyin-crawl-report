# 完整流程细节

从抖音账号 URL 到报告生成的端到端流程，基于「南山鹿」「斗茶谷安安」对标分析项目的实战经验。

## 阶段 0：环境准备

```powershell
# 1. Node.js 加入 PATH（抖音/知乎平台必需）
$env:PATH = "C:\Users\Administrator\AppData\Local\Programs\node-v24.19.0-win-x64;$env:PATH"

# 2. Chrome CDP 模式（端口 9222）
# 地址栏输入 chrome://inspect/#remote-debugging，勾选 "Allow remote debugging"

# 3. 所有命令用 uv run 在项目根目录运行
cd d:\Users\Gao Ming\Documents\SOLO抖音视频号抓取260815
```

## 阶段 1：抓取

### 单个视频（detail 模式）

1. 从视频 URL 提取 `aweme_id`：`https://www.douyin.com/video/{aweme_id}`
2. 运行 detail 抓取
3. 输出：`data/douyin/jsonl/detail_*.jsonl`

### 批量抓取（creator 模式）

1. 从账号 URL 提取 `sec_user_id`：`https://www.douyin.com/user/{sec_uid}`
2. 运行 creator 抓取，`--crawler_max_notes_count` 设为较大值（如 500）
3. **断点续传**：每页抓取后进度写入 `data/douyin/creator_cursor_{sec_uid}.json`，中断后重跑同一命令会自动续传
4. **单会话限制**：约 13 页（~230 条 API）后连接被终止。此时重跑命令，利用断点续传继续抓取剩余视频
5. 抓取完成后断点文件自动删除

### 漏抓兜底：浏览器 fetch 直连（2026-08 新增）

**症状**：creator 模式抓取完成但条数明显少于主页显示数（如 57/162），且无报错。原因：execjs 生成的 `a_bogus` 签名失效，API 静默返回截断数据。

**修复**：用 Playwright `connect_over_cdp` 连浏览器，在页面内 `fetch` 直连 API，复用浏览器自身签名：

```python
# 核心思路（fetch_full.py）
# 1. 连接 CDP 浏览器（勿 browser.close()，会关掉用户 Chrome）
browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
page = ctx.pages[0]
await page.goto(f'https://www.douyin.com/user/{SEC}', wait_until='domcontentloaded')
# 2. 页面内 fetch，关键参数必须齐全
#    from_user_page=1, show_live_replay_strategy=1, need_time_list=1,
#    count=18, publish_video_strategy_type=2
# 3. 逐页循环，max_cursor 翻页，has_more=1 继续
# 4. 复用 MediaCrawler store 的字段提取（anonymize/mask/_extract_*）生成 jsonl
```

**验证**：抓取后按 aweme_id 与旧数据比对覆盖关系，确认字段齐全、时间跨度合理。

### 登录

- 首次运行弹出 QR 码，用抖音 App 扫码
- 登录态缓存在 `config/`，后续运行无需重复登录
- 若登录态过期，重新扫码

## 阶段 2：数据处理

```powershell
# 去重（按 aweme_id）
uv run python dedup_data.py

# 整合多个 jsonl
uv run python consolidate.py

# 下载视频 + 封面（videos/{aweme_id}/）
uv run python download_videos.py

# 图文处理
uv run python make_sheets.py    # 图文拼图 → data/douyin/sheets/
uv run python crop_sheets.py    # 切分格子 → data/douyin/cells/
```

**提速要点**：下载/抽帧/转写脚本均按产物存在性跳过已完成项，换新数据只需重跑一次，增量自动补齐。下载（网络 I/O）与抽帧（CPU）可并行。

## 阶段 3：内容分析

```powershell
# 视频抽帧（第 1 秒代表帧）
uv run python extract_frames.py   # → data/douyin/frames/{aweme_id}.jpg

# 视觉分析（批量推理管线，真实分析）
uv run python gen_vision_part1.py
uv run python improve_part1.py

# BGM 转写与分类（small 模型，快；等口播转写完成后跑避免争抢 CPU）
uv run python transcribe_bgm_all.py

# 口播转写（medium 模型，6 worker CPU 并行，断点续传）
uv run python transcribe_current.py

# 直播话术 docx 提取
uv run python extract_docx.py "直播话术.docx"

# 各维度统计
uv run python analyze_benchmark.py
uv run python analyze_content.py
uv run python analyze_formats.py
uv run python analyze_music.py
uv run python analyze_sales.py
uv run python analyze_time.py
uv run python analyze_top.py
```

## 阶段 4：报告生成

```powershell
# 逐视频分析报告
uv run python generate_per_video_report.py   # → per-video-breakdown.html

# 对标分析报告（人工/Agent 撰写）
# → douyin-tea-benchmark.html
```

对标报告标准章节：账号定位 → 内容矩阵 → 文案写作逻辑 → 带货与变现逻辑 → 衰退归因 → TOP 素材拆解库 → 起号方案。

**提质要点**：报告硬编码数字（总赞/均赞/分类条数/爆款榜/时间范围）必须与最新数据集一致；换新数据后逐段核对封面、概览、趋势、分类、爆款拆解、对标基准、数据来源，避免沿用旧样本。

## 附录：技能内建一键流水线（tools/，2026-08 新增，优先使用）

本技能自带可执行脚本 `tools/`，可脱离特定 MediaCrawler 项目目录独立运行。统一的工作目录结构（`<root>` 为任意工作根，`<account>` 为账号 slug 如 `nutelande`）：

```
<root>/data/douyin/jsonl/*.jsonl         process 读取原始 jsonl
<root>/video-analysis/<account>/manifest.json   process 生成下载清单
<root>/videos/<account>/*.mp4            download 下载视频
<root>/covers/<account>/*.jpg            download 下载封面
<root>/video-analysis/<account>/frames/*.jpg    extract_frames 抽帧
<root>/transcript/<account>/*.txt|.json  transcribe 口播转写
```

从去重到转写的完整命令链：

```powershell
# 0) 给 MediaCrawler 打断点续传补丁（一次性；路径缺省自动探测）
python tools/patch_mediacrawler.py [<MediaCrawler douyin/client.py>]

# 阶段2 去重 + 生成清单（--json 缺省取最新 jsonl）
python tools/process.py --root <root> --account <account>

# 阶段2b 多线程下载（默认3线程，规避CDN风控）
python tools/download.py --root <root> --account <account> [--threads 3]

# 阶段3a 抽帧（默认1fps；PyAV 绕开系统 ffmpeg 无图片编码器）
python tools/extract_frames.py --root <root> --account <account> [--fps 1]

# 阶段3b 口播转写（GPU 自动择优 float16≈快10x；多 worker；断点续传）
python tools/transcribe.py --root <root> --account <account> [--model large-v3] [--workers 2] [--device auto] [--compute auto]
```

要点：
- **环境依赖**：process/download 仅需标准库；extract_frames 需 `av` + `Pillow`；transcribe 需 `faster-whisper`、`ctranslate2`，GPU 另装 `nvidia-cublas-cu12`（脚本自动把其 bin 加入 PATH 以解决 `cublas64_12.dll not found`）。
- **断点续传**：download / extract_frames / transcribe 均按产物已存在自动跳过，换新数据重跑即增量补齐。
- **CPU vs GPU 择优**：transcribe 内部用 `ctranslate2.get_cuda_device_count()` 探测，`--device`/`--compute` 默认 `auto` 自动选 cuda/float16 或 cpu/int8，无需手试。
- **多线程**：download `--threads`（默认3）、transcribe `--workers`（共享单模型，默认2）。
- **报告**：基于 `transcript/` 与 `manifest.json` 撰写，严格遵循 `references/report-template.md` 固定模板；报告用图取 `covers/` 与 `frames/` 的真实素材。
