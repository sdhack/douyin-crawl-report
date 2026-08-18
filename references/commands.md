# 命令速查表

## 运行库解析（本次起，所有 tools/ 脚本统一经此执行）

运行库装在**项目目录 `<项目根>/.runtime/py`**，经全局指针 `~/.trae-cn/runtime-registry.json` 复用（换目录不重装环境、不装 C 盘）。统一前缀：

```bat
set SKILL=C:\Users\Administrator\.trae-cn\skills\douyin-crawl-report
REM 打印运行库解释器 / 校验依赖+CUDA
py -3 %SKILL%\tools\runtime.py py
py -3 %SKILL%\tools\runtime.py doctor
REM 用运行库解释器跑任意工具（等价于旧的：<运行库python> tools\xxx.py ...）
py -3 %SKILL%\tools\runtime.py run --tool transcribe.py --root <工作根> --account <slug> [args]
```

> 优先级：`DOUYIN_RUNTIME_PY` 环境变量 > 全局指针 > 项目 `<root>/.runtime/py`（仅此三档，技能旧 `.venv` 已弃用不参与解析）。

## 第一阶段 · 抓取（技能原生 crawl.py，优先）

`tools/crawl.py` 是技能内建的 MediaCrawler **轻量调度封装**：自动解析 MediaCrawler 解释器/源码根（env > 全局指针 > cache）、拼接经校验的参数、断点续传、进度日志、并把产物落到项目目录（不占 C 盘）。MediaCrawler 本体保留在 `~/.cache/codex-mediacrawler/MediaCrawler`，不随技能复制。

```bat
set SKILL=C:\Users\Administrator\.trae-cn\skills\douyin-crawl-report
REM 账号主页全量（--target 填 sec_uid）
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --max 90
REM 单条视频 / 关键词搜索
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode detail --target "<aweme_id>"
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode search --target "关键词"
REM 用 cookie 复用登录态；或 dry-run 只查看将执行的命令
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --lt cookie --cookies "<cookie串>"
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --dry-run
```

**评论抓取提速（--get-comment + 提速参数，2026-08 落地）**：`detail` 模式 + `--get-comment` 分批补抓评论，配以下提速参数在「更快」与「不被封」间平衡：

```bat
REM 批量补评论：并发=2、每次抓取延时随机取 [3,8]s、失败自动重试2次(指数退避)
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode detail --get-comment --target "<id1>,<id2>,..." --max 100 --speed normal --sleep-min 3 --sleep-max 8 --retry-fail 2
REM 只想并发提速、不改 MediaCrawler 源码延时（涉及 base_config 时）
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode detail --get-comment --target "<id1>,<id2>..." --speed fast --no-mc-patch
```

- `--speed` 预设并发：`safe`=1(默认)/`normal`=2/`fast`=3。`--concurrency` 可显式覆盖。
- `--sleep-min/--sleep-max`：给 MediaCrawler `config/base_config.py` 打一次性 env 补丁（首次备份 `.bak`），使 `MC_SLEEP_SEC` 覆盖其固定 10s；MediaCrawler 内部取 `uniform(0, MC_SLEEP_SEC)`，故该值即本次抓取延时上限，且每批/每次重试重随机。带 `--no-mc-patch` 时不打补丁、延时参数失效（仅并发生效）。
- `--retry-fail N`：进程非 0 退出/超时自动重试 N 次，指数退避（5s→10s→20s→…封顶 60s）。
- `--comments-count N`（默认 100）：抖音**出厂单视频评论上限 10 条**，本参数通过给 MediaCrawler `config/base_config.py` 打 `MC_COMMENTS_COUNT` env 补丁（自动备份 `.bak`）突破，按活动/爆款视频可捞满 N 条。`--max` 仍控聚合并入时每视频计数上限。
- 评论模式产物判定看 `detail_comments_*.jsonl`（不对评论做账号关键词过滤），成功即 `exit 0`，输出 `comments.py` 下一阶段命令。

产物：`<root>/crawl_<account>/`（原始 jsonl + `<account>_dedup.jsonl` 过滤去重 + crawl.log）。下一阶段自动提示 `process.py`（评论模式则提示 `comments.py`）命令。

## MediaCrawler 抓取（底层参考，一般不直接手敲）

> **注意（实战踩坑 2026-08-18）**：① 平台枚举是 `dy`（**不是** `douyin`，否则 `click` 报 `'douyin' is not one of 'xhs','dy',...`）；② creator 批量用 **`--creator_id`**（支持 URL 或 sec_uid），**不用** `--keywords`；③ 条数用 **`--crawler_max_notes_count`**（没有 `--max_pages`）；④ 必须**在 MediaCrawler 根目录运行**（相对引用 `libs/douyin.js`），启用 `MEDIACRAWLER_PY`/`MC_ROOT` 或全局指针定位；⑤ 登录用 `--lt qrcode|cookie|phone`，`--cookies` 传 cookie 串。

## 抓取异常处理（漏抓/截断）

抓取完成后必须与主页显示的视频数核对。发现漏抓/截断时**优先修 MediaCrawler 自身**——核对签名参数（`browser_version`/`os_name`/`pc_libra_divert`）与分页参数（`from_user_page=1`、`show_live_replay_strategy=1`、`need_time_list=1`、`count=18`、`publish_video_strategy_type=2`）并修复后重抓，**不切浏览器兜底**（历史曾用浏览器内 `fetch` 直连 API 临时救急，已弃用）。

## 常用 CLI 参数

| 参数 | 说明 |
|---|---|
| `--platform` | `dy`（抖音）/ `xhs` / `ks` / `bili` / `wb` / `tieba` / `zhihu` |
| `--type` | `search` / `detail` / `creator` |
| `--specified_id` | detail 模式的视频/帖子 ID（逗号分隔） |
| `--creator_id` | creator 模式的创作者 ID（逗号分隔） |
| `--crawler_max_notes_count` | 最大抓取数 |
| `--save_data_option` | `jsonl`（默认）/ `csv` / `db` / `excel` 等 |
| `--get_comment` | 是否抓取一级评论（默认 True） |

## URL → ID 提取

| 类型 | URL 格式 | 提取 |
|---|---|---|
| 账号主页 | `https://www.douyin.com/user/{sec_uid}` | `sec_uid`（用于 `--creator_id`） |
| 单个视频 | `https://www.douyin.com/video/{aweme_id}` | `aweme_id`（用于 `--specified_id`） |

## 技能内建脚本（tools/，2026-08 新增，优先使用）

全流程脚本随技能自带，基于统一 `<root>` + `<account>` 参数运行，详见 `workflow.md` 附录。下表命令中的 `python` 一律指**运行库解释器**（`py -3 <skill>\tools\runtime.py py`），可直接写作 `runtime.py run --tool <x.py>`。

| 脚本 | 命令 | 产出 |
|---|---|---|
| `tools/crawl.py` | `runtime.py run --tool crawl.py --root <root> --account <slug> --mode creator\|detail\|search --target <sec_uid\|aweme_id\|关键词> [--max N] [--get-comment] [--speed safe\|normal\|fast\|--concurrency N] [--sleep-min F --sleep-max F] [--retry-fail N] [--no-mc-patch] [--lt cookie --cookies "…"] [--dry-run]` | 抓取 → `<root>/crawl_<account>/`（原始 jsonl + 过滤去重 + crawl.log）；评论模式另看 `detail_comments_*.jsonl` |
| `tools/patch_mediacrawler.py` | `python tools/patch_mediacrawler.py [<client.py>]` | 给 MediaCrawler 打断点续传补丁（一次性） |
| `tools/process.py` | `python tools/process.py --root <root> --account <slug> [--json <jsonl>]` | 去重→排序→`manifest.json` |
| `tools/download.py` | `python tools/download.py --root <root> --account <slug> [--threads 3]` | 多线程下载视频+封面 |
| `tools/extract_frames.py` | `python tools/extract_frames.py --root <root> --account <slug> [--fps 1] [--workers 4]` | PyAV 抽帧（多进程并行，默认 min(CPU核,4)） |
| `tools/transcribe.py` | `python tools/transcribe.py --root <root> --account <slug> [--model large-v3] [--workers 2] [--device auto] [--compute auto] [--map <term_map.json>]` | 口播转写（GPU 择优 + 断点续传；`--map` 术语纠错订正误识） |
| `tools/transcribe_bgm.py` | `python tools/transcribe_bgm.py --root <root> --account <slug> [--workers 2] [--device auto] [--compute auto]` | BGM 归档（风格/mood/歌词线索，**模型固定 large-v3**，与口播一致免联网）→ `<root>/bgm/<account>/` |
| `tools/bgm_cross.py` | `python tools/bgm_cross.py --root <root> --account <slug> [--top 10]` | BGM×互动交叉（按 bgm_level/mood/vocal 分组算均赞/均藏/均享 + 爆款明细）→ `<root>/bgm/<account>/_cross.json` |
| `tools/comments.py` | `python tools/comments.py --root <root> --account <slug> [--max 100]` | 评论聚合（`detail_comments_*.jsonl` 按视频归并、每视频按赞降序截断 top N）→ `<root>/video-analysis/<account>/comments.json` |
| `tools/decompose_prep.py` | `python tools/decompose_prep.py --root <root> --account <slug>` | 组装每视频全维度档案（标题/时长/时间/互动/口播/帧路径/BGM/评论）→ `decompose/<account>/video_profiles.{json,md}` |
| `tools/account_metrics.py` | `python tools/account_metrics.py --root <root> --account <slug>` | 从 `video_profiles.json` **自动聚合账号级关键维度**：**① 发布节奏**（首/末条日期、跨度、月均、峰值月份、相邻发布间隔中位，仅到日期无小时）、**② 互动交叉聚类**（收藏/评论/分享率中位整体结构 + 爆款型/收藏型/讨论型/分享转执型 Top5，账号自适应中位数+相对突出度阈值，长尾也命中）、**③ 话题策略 + 高赞评论**（#hashtag 词频+均赞 Top15 + 全账号高赞评论 Top20）→ `decompose/<account>/_metrics.json`，博主人总结必吃数据 |
| `tools/render_report.py` | `python tools/render_report.py --source 对标分析报告.md` **或** `... | python tools/render_report.py --stdin --out 报告.html`（**直接出 html、不落 md 中间稿**）`[--key 'DOUYIN BENCHMARK'] [--no-toc] [--title …] [--tagline …] [--inline]` | 对标报告 md/内容 → **自包含单文件 HTML**，对齐 `report-template.md`：目录只收主章节、`## N *单位*` 数据样本卡、`# 数字` 居中大数字卡、`## 01~07` section、`>` 五类收治区自动配色、**嵌套列表 → 内容支柱树**、真实抽帧图 `--inline` 内联 base64（**唯一官方 HTML 渲染入口，禁止手工平铺**）；`--no-toc` 去掉侧栏目录、章节不再套卡片盒，改单栏+顶部品牌横幅的扁平版式（博主全量视频总结默认用它）；**每次渲染默认从内置 8 套视觉主题中随机挑一套（内容骨架恒定、视觉不重样），用 `--theme <name>` 指定、`--theme-seed <N>` 固定复现** |
| `references/blogger-summary-prompt.md` | 账号级总结提示词（见该文件）：对全量 `tags.json`+`comments.json`+`video_profiles` 按 11 节「博主全量视频总结」分析→**直接经 `render_report.py --stdin --key 'CREATOR SUMMARY'` 出 html（不落 md）** | 账号内容增长模型 / 内容DNA / 机会挖掘的多维度总结报告 |

**资源自适应调度（tools/probe.py）**：`download --threads`、`extract_frames --workers`、`transcribe --workers` 缺省按机器配置自动取值——`CPU 核数 + 内存占用率(可用GB) + GPU 有无`。GPU 存在→转写 worker 少（共享显存，宜 2）；无 GPU→CPU 用剩余核并切 int8 且按内存封顶；抽帧按 `min(核,4)` 且受可用内存约束防 OOM。显式传参可覆盖推荐值。

**tools/ 数据目录约定**：

| 路径 | 内容 |
|---|---|
| `<root>/video-analysis/<account>/manifest.json` | 下载清单（含互动指标、URL，按赞排序） |
| `<root>/video-analysis/<account>/frames/<aweme_id>/*.jpg` | 抽帧（1fps） |
| `<root>/videos/<account>/*.mp4` | 视频 |
| `<root>/covers/<account>/*.jpg` | 封面 |
| `<root>/transcript/<account>/*.txt \| *.json` | 口播逐字稿 + 结构化 JSON |
| `<root>/bgm/<account>/*.json \| _manifest.json` | BGM 归档（bgm_level/vocal/mood/歌词线索）+ 聚合统计 |
| `<root>/bgm/<account>/_cross.json` | BGM×互动交叉（bgm_cross.py：组间均赞/均藏/均享、爆款明细） |
| `<root>/video-analysis/<account>/comments.json` | 评论聚合（comments.py：每视频按赞截断 top N） |
| `<root>/decompose/<account>/video_profiles.{json,md}` | 每视频全维度档案（decompose_prep.py，供拆解取数） |
| `<root>/decompose/<account>/tags.json` | 全量标准化标签（单视频拆解第11节18字段，供账号聚合） |
| `<root>/decompose/<account>/_metrics.json` | 账号级聚合（account_metrics.py：发布节奏 / 互动交叉聚类 / 话题策略 / 高赞评论Top20，博主总结必吃） |

> **报告渲染**：对标报告按 `references/report-template.md` 固定模板撰写；HTML **一律用技能内建 `tools/render_report.py`** 渲染为**自包含单文件**（对齐模板结构；`--inline` 把抽帧/封面内联 base64、BGM 条形图用 CSS 变量 `var(--accent)` 调色，一处改色全篇跟随）。

**tools/ 环境依赖**：`extract_frames` 需 `av`+`Pillow`；`transcribe` 需 `faster-whisper`+`ctranslate2`，GPU 另装 `nvidia-cublas-cu12`（解决 `cublas64_12.dll not found`，脚本自动把 bin 加入 PATH）。
