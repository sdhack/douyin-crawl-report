# 命令速查表

## MediaCrawler 抓取

| 场景 | 命令 |
|---|---|
| 单个视频 | `uv run main.py --platform dy --lt qrcode --type detail --specified_id "{aweme_id}" --crawler_max_notes_count 1` |
| 批量（账号主页） | `uv run main.py --platform dy --lt qrcode --type creator --creator_id "{sec_uid}" --crawler_max_notes_count 500` |
| 关键词搜索 | `uv run main.py --platform dy --lt qrcode --type search --keywords "关键词" --crawler_max_notes_count 30` |
| Cookie 登录 | `uv run main.py --platform dy --lt cookie --cookies "{cookie串}" --type creator --creator_id "{sec_uid}"` |

## 漏抓兜底（浏览器 fetch 直连，2026-08 新增）

| 脚本 | 用途 |
|---|---|
| `fetch_full.py` | 签名失效时，Playwright 连 CDP 浏览器，页面内 fetch 直连 `aweme/v1/web/aweme/post/` 逐页抓全（复用浏览器签名）。**勿调用 `browser.close()`**，会关掉用户 Chrome。 |
| `fetch_pages.py` | 诊断分页：验证浏览器直连可获取完整数据、核对 `has_more`/`max_cursor` 逻辑。 |

关键请求参数（缺一可能导致截断/提前终止）：`from_user_page=1`、`show_live_replay_strategy=1`、`need_time_list=1`、`count=18`、`publish_video_strategy_type=2`。

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

## 数据处理与分析

| 脚本 | 用途 |
|---|---|
| `dedup_data.py` | 按 aweme_id 去重 → `*_dedup.jsonl` |
| `consolidate.py` | 合并多个 jsonl |
| `download_videos.py` | 下载视频/封面 → `videos/`（按产物存在性跳过，断点续传） |
| `make_sheets.py` / `crop_sheets.py` | 图文拼图与切分 |
| `extract_frames.py` | 视频抽帧 → `data/douyin/frames/`（第 1 秒代表帧，跳过已有） |
| `transcribe_current.py` | 口播逐字稿转写（medium，6 worker CPU 并行，断点续传）→ `data/transcriptions.json` |
| `transcribe_bgm_all.py` | BGM 批量转写与分类（small 模型，快） |
| `extract_docx.py` | 直播话术 docx 文本提取 |
| `analyze_*.py` | 各维度统计 |
| `generate_per_video_report.py` | 逐视频报告 → `per-video-breakdown.html` |
| `gen_report_assets.py` | 聚合报告数据 → `assets/data.js`（speech/BGM/排行） |

## 数据目录约定

| 路径 | 内容 |
|---|---|
| `data/douyin/jsonl/` | 抓取原始数据（JSONL） |
| `data/douyin/creator_cursor_{sec_uid}.json` | 批量抓取断点文件 |
| `data/douyin/frames/` | 视频抽帧 |
| `data/douyin/sheets/` `cells/` | 图文拼图/格子图 |
| `data/douyin/per_video_analysis.json` | 逐视频视觉/BGM 分析 |
| `videos/{aweme_id}/` | 下载的视频与封面 |
