# Agent 分发与兼容性说明

本技能面向不同能力的 Agent 分发时，遵循以下运行约定：

## 最小能力

- 仅抓取公开抖音内容；不要求 Agent 具备浏览器控制能力。
- `tools/runtime.py` 负责解析项目运行库和 MediaCrawler，优先使用环境变量，其次使用全局注册表，最后使用项目 `.runtime/py`。
- 无 GPU 时，口播与 BGM 转写自动降级到 CPU/int8；缺少转写依赖时应先运行 `runtime.py doctor`，不能伪造转写结果。
- 没有登录态时，允许生成公开元数据、视频、抽帧和不依赖评论的报告；评论章节必须标记缺源。

## 路径与命名

- `--root` 首次表示运行目录父目录；`crawl.py` 创建 `<root>/<account>-YYYYMMDD-HHMMSS/` 和 `.douyin-crawl-run.json` 后，该目录是整轮唯一工作根。后续 `crawl.py` 评论/续跑用 `--run-dir` 复用；其他工具把它作为 `--root`。已有运行根不得嵌套创建新时间戳目录。
- `--account` 只用于目录命名，不参与视频内容过滤；视频唯一性始终按 `aweme_id` 判断。
- 每个账号必须使用唯一 `--account` slug。`crawl.py` 在 `<root>/accounts/<slug>.json` 记录并绑定 creator `sec_uid`；同一 slug 指向另一个账号时立即拒绝。
- `process.py` 自动读取当前 `crawl_<account>/douyin/jsonl/`；旧共享目录所有权不明确，必须显式传 `--json`。
- `comments.py` 只扫描当前 `crawl_<account>/`，并按当前 manifest 的 `aweme_id` 再过滤一次。
- `tools/analyze.py` 提供统一分析入口：抽帧与口播转写并行，BGM 串行；任一阶段失败立即非零退出。
- Windows 路径统一通过参数传入；批处理优先使用 Python `subprocess`，避免 PowerShell 中文路径编码问题。

## 能力降级

| 能力 | 可用时 | 不可用时 |
|---|---|---|
| MediaCrawler | 抓取账号/视频及可选评论 | 立即非零退出并报告错误；不切浏览器 API、网页抓取或其他兜底 |
| GPU/CUDA | `large-v3` + CUDA/float16 | `large-v3` + CPU/int8，或声明转写依赖缺失 |
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

1. 抽帧和口播转写并行；
2. 两者均成功后执行 BGM；
3. 任一阶段失败立即退出，不执行兜底。

使用 `--skip-bgm` 可只执行抽帧和口播转写。GPU 机器默认保持较低转写并发，避免口播和 BGM 同时争抢显存。

## 多账号目录隔离

每个账号使用唯一 slug，例如 `eguo-official`、`creator-gaozhikai`。同一工作根内的产物按账号隔离：

```text
<root>/<account>-YYYYMMDD-HHMMSS/
├─ accounts/<account>.json
├─ crawl_<account>/
├─ video-analysis/<account>/
├─ videos/<account>/
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
