# 命令速查表

## 运行库解析（本次起，所有 tools/ 脚本统一经此执行）

运行库装在**项目目录 `<项目根>/.runtime/py`**，经全局指针 `~/.trae-cn/runtime-registry.json` 复用（换目录不重装环境、不装 C 盘）。统一前缀：

```bat
set SKILL=%USERPROFILE%\.trae-cn\skills\douyin-crawl-report
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
set SKILL=%USERPROFILE%\.trae-cn\skills\douyin-crawl-report
REM 账号主页全量（--target 填 sec_uid）
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --max 90
REM 单条视频 / 关键词搜索
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode detail --target "<aweme_id>"
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode search --target "关键词"
REM 用 cookie 复用登录态；或 dry-run 只查看将执行的命令
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --lt cookie --cookies "<cookie串>"
py -3 %SKILL%\tools\runtime.py run --tool crawl.py --root <根> --account <slug> --mode creator --target "<sec_uid>" --dry-run
```

**评论抓取提速（默认开启、每视频 100 条）**：抓取命令默认带评论，`--comments-count` 默认 100；仅在明确不需要评论时传 `--no-comment`。配以下参数在「更快」与「不被封」间平衡：

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

产物：`<run-root>/crawl_<account>/`（原始 jsonl + `<account>_dedup.jsonl` 过滤去重 + crawl.log）。下一阶段命令中的 `--root` 使用控制台打印的本次运行目录。

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
| `tools/crawl.py` | `runtime.py run --tool crawl.py --root <parent> --account <slug> --mode creator\|detail\|search --target <sec_uid\|aweme_id\|关键词> [--max N] [--comments-count 100\|--no-comment] [--speed safe\|normal\|fast\|--concurrency N] [--sleep-min F --sleep-max F] [--retry-fail N] [--no-mc-patch] [--lt cookie --cookies "…"] [--dry-run]` | 默认抓每视频最多 100 条评论；每次创建 `<parent>/<slug>-时间戳/`，后续产物均在该运行目录内 |
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
| `tools/report_html.py` | `python tools/report_html.py --root <root> --account <slug> --title "…" [--subtitle "…"] --narrative <narrative.json> --out 报告.html [--top-n 10] [--frames-n 8] [--img-cap-kb 400] [--design '<json>']` | **对标报告 v2 固定骨架生成器（唯一入口）**：统计数字全部实时计算、多枚 SVG 图表自动生成（周发布/月度趋势/主题环形/点赞分布/BGM 对比/情绪分布）、封面与关键帧自动内联、结构自检；**设计美学完全由 AI 决定**——narrative.json 的 `design` 键或 `--design` 传入 token（缺键回落可读性基线）；narrative 槽位与 token 说明见 `references/report-template.md` |
| `tools/render_report.py` | `python tools/render_report.py --source 总结.md` **或** `... \| python tools/render_report.py --stdin --out 报告.html`（直接出 html、不落 md 中间稿）`[--key 'CREATOR SUMMARY'] [--title …] [--tagline …] [--inline] [--design '<json>'] [--toc]` | **博主全量视频总结 / decompose 长文专用 md→HTML 渲染器**（**三大约束硬性规定**：默认单栏**无目录**（`--no-toc` 即缺省，仅 `--toc` 恢复侧栏）、图片默认「相册网格」两两成排且限高 460px 不突兀、`--design '<json>'` 由 AI 给定整套设计 token 而**骨架全局恒定**；键见 `NEUTRAL_DEFAULT`，漏键回落可读性基线，不做随机轮换；`--inline` 内联 base64）。**不再渲染对标报告**（对标一律走 report_html.py） |
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
| `<root>/video-analysis/<account>/narrative.json` | 对标报告定性槽位（AI 撰写，schema 见 report-template.md v2） |
| `<root>/decompose/<account>/video_profiles.{json,md}` | 每视频全维度档案（decompose_prep.py，供拆解取数） |
| `<root>/decompose/<account>/tags.json` | 全量标准化标签（单视频拆解第11节18字段，供账号聚合） |
| `<root>/decompose/<account>/_metrics.json` | 账号级聚合（account_metrics.py：发布节奏 / 互动交叉聚类 / 话题策略 / 高赞评论Top20，博主总结必吃） |

> **报告渲染分工（v2 收口，防双路径打架）**：**对标分析报告一律走 `tools/report_html.py`**（v2 固定骨架直出自包含单文件，统计数字实时计算、封面/关键帧自动内联、结构自检；定性槽位经 `--narrative` 注入，schema 见 `references/report-template.md`）。`render_report.py` 仅渲染**博主全量视频总结 / decompose 长文**（自由 md，`--inline` 把抽帧/封面内联 base64）。

**tools/ 环境依赖**：`extract_frames` 需 `av`+`Pillow`；`transcribe` 需 `faster-whisper`+`ctranslate2`，GPU 另装 `nvidia-cublas-cu12`（解决 `cublas64_12.dll not found`，脚本自动把 bin 加入 PATH）。
