# 完整流程细节

从抖音账号 URL 到报告生成的端到端流程，基于「南山鹿」「锋味派」「诺特兰德」等对标分析项目的实战经验。本技能自带 `tools/` 一键流水线（见文末附录），统一下述命令均可经 `py -3 <skill>/tools/runtime.py run --tool <x>.py ...` 走项目运行库解释器执行。

## 环境与登录准备

```powershell
# 1. Node.js 加入 PATH（MediaCrawler 抖音 execjs 签名必需）
$env:PATH = "C:\Users\Administrator\AppData\Local\Programs\node-v24.19.0-win-x64;$env:PATH"

# 2. 登录态：首次 qrcode 扫码；后续可复用登录态（cookie/CDP 复用 Edge/Chrome 登录）
#    登录态缓存于 MediaCrawler config/，过期则重新扫码
```

> 抓取异常/漏抓时**优先修 MediaCrawler 自身**（签名/分页参数/登录态），核验真实视频数，**不切浏览器兜底**（历史曾用浏览器内 `fetch` 直连 API 临时救急，已弃用）。

## 阶段 1：抓取（crawl.py）

### 单个视频（detail 模式）

1. 从视频 URL 提取 `aweme_id`：`https://www.douyin.com/video/{aweme_id}`
2. 运行 detail 抓取（`--target <aweme_id>` 或逗号分隔多个）
3. 产物：`<root>/crawl_<account>/` 原始 jsonl

### 批量抓取（creator 模式）

1. 从账号 URL 提取 `sec_user_id`：`https://www.douyin.com/user/{sec_uid}`
2. 运行 creator 抓取（`--target "<sec_uid>" --max N`）
3. **断点续传**：进度写入 `<root>/crawl_<account>/cursor/`（`MC_CURSOR_DIR` 落项目，不占 cache），中断重跑同一命令自动续传
4. **单会话限制**：约 230 条 API 后连接被终止，重跑命令利用断点续传继续抓剩余
5. 抓取完成后自动过滤去重，产出 `<account>_dedup.jsonl`；`--dry-run` 可先预览命令

### 评论补抓（--get-comment，评论区分析前提）

- 对标拆解要做评论区分析时，用 **detail 模式 + `--get-comment`** 对全量 `aweme_id` 分批补抓（每次逗号分隔成批、`--max` 控每条视频上限），落 `detail_comments_*.jsonl`。
- **提速参数**（更快与不被封兼得）：`--speed normal|fast`（并发 2/3）、`--sleep-min 3 --sleep-max 8`（随机延时覆盖 MediaCrawler 固定 10s）、`--retry-fail 2`（指数退避重试）、`--comments-count 100`（突破出厂单视频 10 条评论上限）。
- 评论 API 需登录态；追账期内可直接复用登录态，无需重复扫码。
- **注意**：批处理循环用 python 脚本（`subprocess`）驱动，勿用 `powershell -File` 拼中文路径（代码页会乱码导致整脚本早退）。
- 产物判定看 `detail_comments_*.jsonl`（不对评论做账号关键词过滤），成功即 `exit 0`，自动提示下一步 `comments.py` 命令。

### 抓取质量校验（必做）

- **核实真实视频数**：抓取完成后必须与主页显示的视频数核对，防止签名失效导致的静默漏抓（曾只抓到 57/162 条）。
- 新抓数据需按 aweme_id 覆盖旧数据，字段齐全、时间跨度合理才算完成。

## 阶段 2：数据处理（process.py → download.py）

1. `process.py`：对去重 jsonl 按 aweme_id 去重 → 互动指标换算 → 按赞排序 → 生成下载清单 `video-analysis/<account>/manifest.json`
2. `download.py`：多线程下载视频 + 封面 → `videos/<account>/`、`covers/<account>/`（并发默认按机器配置 2~6，规避 CDN 风控；按产物存在性跳过，断点续传）

## 阶段 3：内容分析

1. `extract_frames.py`：PyAV 1fps 抽帧（绕开精简版 ffmpeg 无图片编码器）→ `video-analysis/<account>/frames/<aweme_id>/*.jpg`（多进程并行，默认 min(CPU核,4) 且受可用内存约束）
2. `transcribe.py`：口播逐字稿 → `transcript/<account>/{aweme_id}.txt|.json`（GPU 自动择优 float16≈快 10x，断点续传；`--map <term_map.json>` 订正专业名词误识，{误词:正词}）
3. `transcribe_bgm.py`：BGM 归档 → `bgm/<account>/{aweme_id}.json + _manifest.json`（bgm_level none/light/full · vocal speech/singing/none · mood · 歌词线索；**模型固定 large-v3**，与口播一致已缓存免联网）
4. `bgm_cross.py`：BGM×互动交叉 → `bgm/<account>/_cross.json`（by_level/by_mood/by_vocal 组内 n/pct/均赞/均藏/均享 + 爆款明细 + 轻BGM vs 纯口播倍数）
5. （如需评论区）`comments.py`：`detail_comments_*.jsonl` 按视频归并、每视频按赞降序截断 top N → `video-analysis/<account>/comments.json`

**提速要点**：下载/抽帧/转写均按产物存在性跳过已完成项，换新数据只跑增量；下载（网络 I/O）与抽帧（CPU）可并行；BGM 转写等口播转写完成后跑，避免争抢 CPU。

## 阶段 4：报告生成（render_report.py，直接出 HTML）

对标分析报告**必须遵循 `references/report-template.md` 固定模板**（文档头→引言→数据样本构成→关键指标→核心结论→01~07 章节→附言）。HTML **一律用技能内建 `tools/render_report.py`** 一步渲染为自包含单文件，不落 `.md` 中间稿：

```powershell
# 推荐：内容完成后直接经 --stdin 渲染，工作区只留 .html
Get-Content 分析内容.md -Raw | py -3 <skill>\tools\runtime.py run --tool render_report.py --stdin --out "{账号}-对标分析报告.html" [--key 'DOUYIN BENCHMARK'] [--no-toc]
# 或先落一份 .md 再渲染
py -3 <skill>\tools\runtime.py run --tool render_report.py --source 对标分析报告.md [--out 对标分析报告.html] [--inline]
```

- `--inline`：封面/抽帧内联 base64，保持单文件；`--no-toc`：去掉侧栏目录（单栏+顶部品牌横幅，博主全量视频总结默认用它）；`--title/--tagline` 可覆盖侧栏标题与副题。
- 渲染对齐 report-template：目录只收主章节 `## 01~07`、`## N *单位*` 数据样本卡、章内 `# 数字` 居中大数字卡、`>` 五类收治区自动配色、嵌套列表→内容支柱树。
- **每次渲染默认从内置 8 套视觉主题中随机轮换**（内容骨架恒定、视觉不重样），用 `--theme <name>` 指定、`--theme-seed <N>` 复现。

**提质要点**：报告硬编码数字（总赞/均赞/分类条数/爆款榜/时间范围）必须与最新数据集一致；换新数据后逐段核对封面、概览、趋势、分类、爆款拆解、对标基准、数据来源，避免沿用旧样本。

## 阶段 4b：单视频逆向拆解 + 账号总结

按 `references/decompose-methodology.md` 补齐数据链：

1. `decompose_prep.py`：组装每视频全维度档案中控 → `decompose/<account>/video_profiles.{json,md}`（标题/时长/时间/互动/口播/帧路径/BGM/评论）
2. 全量每条第 11 节标准化标签 → `decompose/<account>/tags.json`
3. 爆款 TOP + 典型全套 11 节深拆（配真实关键帧）

## 阶段 4b2：账号级自动聚合（博主总结前置必跑）

`account_metrics.py`：从 `video_profiles.json` 自动聚合 → `decompose/<account>/_metrics.json`，博主总结提示词视为**必吃数据**：

- **① 发布节奏**：首/末条日期、跨度、月均、峰值月份、相邻发布间隔中位（诚实标注仅到日期无小时）
- **② 互动交叉聚类**：整体互动结构（收藏/评论/分享率中位 + 最高赞单条占比）+ 爆款/收藏型/讨论型/分享转执型 Top5（账号自适应中位数 + 相对突出度，长尾也命中）
- **③ 话题策略 + 高赞评论**：#hashtag 词频+均赞 Top15 + 全账号高赞评论 Top20（含原文/所属标题/点赞）

## 阶段 4c：博主全量视频总结 → 账号级 HTML

按 `references/blogger-summary-prompt.md` 的 11 节提示词，用全量 `tags.json` + `comments.json` + `video_profiles` + `_metrics.json` 产出账号级总结，`_metrics.json` 的 发布节奏/互动交叉聚类/话题策略/高赞评论 直接落到 二/六/七 等章节；**直接经 `render_report.py --stdin --key 'CREATOR SUMMARY'` 出 html（不落 md）**。

---

## 附录：技能内建一键流水线（tools/）

统一的工作目录结构（`<root>` 为任意工作根，`<account>` 为账号 slug 如 `nutelande`）：

```
<root>/crawl_<account>/                    crawl 抓取产物（原始 jsonl + 去重 + crawl.log）
   └─ cursor/                              断点续传文件（MC_CURSOR_DIR 落项目，不占 cache）
<root>/video-analysis/<account>/manifest.json   process 下载清单（互动排序）
<root>/video-analysis/<account>/frames/<aid>/*.jpg  extract_frames 抽帧
<root>/video-analysis/<account>/comments.json  comments 评论聚合（每视频按赞截断 top N）
<root>/videos/<account>/*.mp4              download 视频
<root>/covers/<account>/*.jpg              download 封面
<root>/transcript/<account>/*.txt|.json    transcribe 口播转写
<root>/bgm/<account>/*.json|_manifest.json  transcribe_bgm BGM 归档
<root>/bgm/<account>/_cross.json           bgm_cross BGM×互动交叉
<root>/decompose/<account>/video_profiles.{json,md}   decompose_prep 全维度档案
<root>/decompose/<account>/tags.json       全量标准化标签
<root>/decompose/<account>/_metrics.json   account_metrics 账号级聚合
```

完整命令链（`python` 一律指运行库解释器，或写成 `py -3 <skill>\tools\runtime.py run --tool <x.py>`）：

```powershell
# 1 抓取（--dry-run 先预览命令）
python tools/crawl.py --root <root> --account <account> --mode creator --target "<sec_uid>" [--max N] [--lt cookie --cookies "…"] [--dry-run]
python tools/crawl.py --root <root> --account <account> --mode detail --target "<aweme_id>"
python tools/crawl.py --root <root> --account <account> --mode search --target "关键词"
#    评论补抓：--mode detail --get-comment --target "<id1>,<id2>,..." --max 100 --speed normal --sleep-min 3 --sleep-max 8 --retry-fail 2

# 0 给 MediaCrawler 打断点续传补丁（一次性；路径缺省自动探测）
python tools/patch_mediacrawler.py [<MediaCrawler douyin/client.py>]

# 2 去重 + 生成清单（--json 缺省取最新 jsonl）
python tools/process.py --root <root> --account <account>
# 2b 多线程下载视频+封面（并发自适应，默认 min(核,6)）
python tools/download.py --root <root> --account <account>

# 3a 抽帧（默认1fps；多进程，默认 min(CPU核,4) 且受内存约束）
python tools/extract_frames.py --root <root> --account <account> [--fps 1]
# 3b 口播转写（GPU 自动择优 float16；断点续传；--map 订正术语误识）
python tools/transcribe.py --root <root> --account <account> [--model large-v3] [--map <term_map.json>]
# 3c BGM 归档（模型固定 large-v3）
python tools/transcribe_bgm.py --root <root> --account <account>
# 3d BGM×互动交叉
python tools/bgm_cross.py --root <root> --account <account> [--top 10]
# 3e 评论聚合（前提：先把评论补抓落 detail_comments_*.jsonl）
python tools/comments.py --root <root> --account <account> [--max 100]

# 4 报告生成（对标 → 干净卡片式 HTML，直接出 html 不落 md）
Get-Content 分析内容.md -Raw | python tools/render_report.py --stdin --out 对标分析报告.html [--key 'DOUYIN BENCHMARK'] [--no-toc]

# 4b 单视频逆向拆解（见 decompose-methodology.md）
python tools/decompose_prep.py --root <root> --account <account>
# 4b2 账号级自动聚合（博主总结前置必跑）
python tools/account_metrics.py --root <root> --account <account>
# 4c 博主全量视频总结 → 账号级 HTML（提示词见 blogger-summary-prompt.md）
Get-Content 博主全量视频总结.md -Raw | python tools/render_report.py --stdin --out "博主全量视频总结.html" --key 'CREATOR SUMMARY'
```

要点：

- **环境依赖**：process/download 仅需标准库；extract_frames 需 `av` + `Pillow`；transcribe 需 `faster-whisper`、`ctranslate2`，GPU 另装 `nvidia-cublas-cu12`（脚本自动把其 bin 加入 PATH 解决 `cublas64_12.dll not found`）。
- **断点续传**：download / extract_frames / transcribe 均按产物已存在自动跳过，换新数据重跑即增量补齐。
- **CPU vs GPU 择优**：transcribe 用 `ctranslate2.get_cuda_device_count()` 探测，`--device`/`--compute` 默认 `auto` 自动选 cuda/float16 或 cpu/int8。
- **并发自适应（推荐）**：download/extract_frames/transcribe 的并发缺省由 `tools/probe.py` 按 CPU 核数 + 内存占用率 + GPU 有无自动调度，显式传参可覆盖。
- **报告**：基于 `transcript/`（话术）、`manifest.json`（互动）、`bgm/_cross.json`（BGM×互动实证）撰写，严格遵循 `references/report-template.md`；用图取 `covers/` 与 `frames/` 真实素材，`--inline` 内联 base64 保单文件。
- **博主总结（阶段4b2 前置必跑）**：做账号级总结前必须先跑 `account_metrics.py` 生成 `_metrics.json`。三地映射：**发布节奏→二·选题地图(时间轴)**、**互动交叉聚类→七·爆款VS普通(分型)**、**话题策略+高赞评论→六·用户需求地图(评论区实证)**。