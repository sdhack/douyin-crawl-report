# Agent 分发与兼容性说明

本技能面向不同能力的 Agent 分发时，遵循以下运行约定：

## 最小能力

- 仅抓取公开抖音内容；不要求 Agent 具备浏览器控制能力。
- `tools/runtime.py` 负责解析项目运行库和 MediaCrawler，优先使用环境变量，其次使用全局注册表，最后使用项目 `.runtime/py`。
- 无 GPU 时，口播与可选 BGM ASR 自动降级到 CPU/int8；抽帧 GPU 不可用时自动走 PyAV CPU；缺少转写依赖时应先运行 `runtime.py doctor`，不能伪造转写结果。
- 没有登录态时，允许生成公开元数据、视频、抽帧和不依赖评论的报告；评论章节必须标记缺源。

## 路径与命名

- `--root` 首次表示父目录；父目录通过 `.douyin-crawl-current-<account>.json` 为所有 Agent 共享当前运行根。默认复用，只有用户明确要求新一轮时用 `--new-run`。创建过程有账号级锁；不得在运行根内嵌套时间戳目录。
- `--account` 只用于目录命名，不参与视频内容过滤；视频唯一性始终按 `aweme_id` 判断。
- 每个账号必须使用唯一 `--account` slug。`crawl.py` 在 `<root>/accounts/<slug>.json` 记录并绑定 creator `sec_uid`；同一 slug 指向另一个账号时立即拒绝。
- `process.py` 自动读取当前 `crawl_<account>/douyin/jsonl/`；旧共享目录所有权不明确，必须显式传 `--json`。
- `comments.py` 只扫描当前 `crawl_<account>/`，并按当前 manifest 的 `aweme_id` 再过滤一次。
- `tools/analyze.py` 提供统一分析入口：先复用 `media-audio/<account>/published/<url_hash>.mp3` 作为发布成片混合音轨进行口播转写，随后 NVDEC/`scale_cuda` 自适应抽帧与混合音轨非口播区间 BGM 证据分析并行，最后逐帧画面指标与字幕 OCR；任一阶段失败立即非零退出。视觉摘要由报告生成器读取并进入内容矩阵/爆款对比。
- Windows 路径统一通过参数传入；批处理优先使用 Python `subprocess`，避免 PowerShell 中文路径编码问题。

## 能力降级

| 能力 | 可用时 | 不可用时 |
|---|---|---|
| MediaCrawler | 抓取账号/视频及可选评论 | 立即非零退出并报告错误；不切浏览器 API、网页抓取或其他兜底 |
| GPU/CUDA | `large-v3` + CUDA/float16 | `large-v3` + CPU/int8，或声明转写依赖缺失 |
| FFmpeg CUDA/NVDEC | `extract_frames.py --device auto|cuda` 的代理检测与高清候选提取 | 单视频自动 PyAV CPU 回退；`frames.json` 写入 `backend` 与 `fallback_reason` |
| 评论登录态 | 评论抓取与聚合 | 报告保留缺源声明，不推断用户声音 |
| 真实视频/抽帧 | 视觉证据与报告图片 | 删除或明确标记缺失，不生成替代图片 |

## 发布前检查

1. Git Commit 标题和说明必须使用中文，清楚描述用户可感知的改动；禁止使用英文 Conventional Commit 标题。
2. 每次提交必须同时修改 `README.md`，至少更新版本徽章、功能说明或“更新日志”中的一项；不允许代码已变而 README 无记录。
3. 发布版本时同步更新 `manifest.json` 版本号与 README 版本徽章。
4. 在全新工作根目录运行 `runtime.py doctor`。
5. 用 `process.py --root <root> --account <slug>` 验证 JSONL 发现与账号隔离。
6. 检查 `aweme_id` 去重、视频 URL 缺失统计和失败产物列表。
7. 报告中的数字必须由管线产物计算，缺源必须显式声明。

## 一键分析调度

下载完成后可运行：

```bash
python tools/analyze.py --root <root> --account <slug>
```

调度顺序固定为：

1. 口播音频转写（优先 `published_audio_url`/兼容 `music_download_url`，缓存到 `media-audio/<account>/published/<url_hash>.mp3`；失败后才用本地视频提取，再用 `speech_url` 远程视频；图文跳过）；
2. NVDEC/`scale_cuda` 自适应抽帧与混合音轨非口播证据分析并行（BGM 复用 published 文件，按 transcript segments 排除口播窗口；默认不做第二次 ASR，证据不足标记 `unknown/证据不足`）；
3. 逐帧画面指标与字幕 OCR。

任一阶段失败立即退出，不执行全局兜底；抽帧 GPU 只在单视频级别回退 CPU，损坏视频仍 fail-loud。默认 BGM 不加载 ASR，兼容参数 `--music-asr` 会被忽略，因此可与抽帧并行且不争抢显存。使用 `--skip-bgm` 可跳过 BGM 阶段，口播转写、抽帧与画面分析照常执行。

## 多账号目录隔离

每个账号使用唯一 slug，例如 `eguo-official`、`creator-gaozhikai`。同一工作根内的产物按账号隔离：

```text
<root>/<account>-YYYYMMDD-HHMMSS/
├─ accounts/<account>.json
├─ crawl_<account>/
├─ video-analysis/<account>/
├─ videos/<account>/
├─ media-audio/<account>/published/ # 发布成片混合音轨 mp3（口播/BGM 共享）
├─ covers/<account>/
├─ transcript/<account>/
├─ bgm/<account>/
├─ decompose/<account>/
└─ reports/<account>/
```

抓取结束后请使用控制台打印的“本次运行目录”作为后续 `process.py`、`analyze.py` 和报告工具的 `--root`。报告建议输出到 `<run-root>/reports/<account>/`。禁止为不同 creator 复用同一个 slug；身份冲突时工具直接退出，不合并历史数据。

## MediaCrawler 硬失败策略

MediaCrawler 是唯一允许的抓取引擎。以下任一情况都必须立即结束抓取阶段并返回非零退出码：

- 未找到 MediaCrawler 解释器或源码根；
- MediaCrawler 子进程无法启动；
- MediaCrawler 子进程超时、崩溃或返回非零退出码；
- 抓取进程返回成功但没有产生预期 JSONL 产物。

失败后不得读取旧的 JSONL 继续处理，也不得调用浏览器内 `fetch`、Playwright 直连 API、网页解析器或其他隐式兜底。修复 MediaCrawler、登录态、签名或分页参数后重新运行。
