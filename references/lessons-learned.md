# 经验教训

## 抓取阶段

- **单会话 ~230 条限制**：抖音爬虫 API 单会话约 13 页（~230 条）后连接被终止。批量抓取必须分多次运行，每次重跑同一命令利用断点续传继续，直到断点文件自动删除（表示抓取完成）。
- **频率控制**：请求过于频繁会触发 ArgusSecurityPlugin 拦截。间隔从 2 秒提高到 8–10 秒可显著降低风险。
- **登录态**：登录态缓存在 `config/`，一次扫码长期有效。若中途失效，重新扫码即可，无需重装环境。
- **`a_bogus` 签名失效会静默漏抓**（2026-08 实测）：execjs 生成的签名与真实浏览器环境（UA/硬件信息）不一致时，API 不报错但返回截断数据——曾只抓到 57/162 条，且 `has_more=0` 提前终止，无任何异常提示。**必须与主页显示的视频数核对**，不能只看"抓取完成"。
- **浏览器 fetch 直连（已弃用，仅供历史参考）**：曾作为签名失效时的兜底（用 Playwright `connect_over_cdp` 连浏览器、页面内执行 `fetch` 请求 `aweme/v1/web/aweme/post/` 复用浏览器自身签名一次抓全，关键参数 `from_user_page=1`、`show_live_replay_strategy=1`、`need_time_list=1`、`count=18`）。当前策略已改为「抓取异常先修 MediaCrawler 本身，不切浏览器兜底」，此方案保留为教训记录，勿再作为恢复手段。
- **CDP 误关浏览器**：`browser.close()` 在 `connect_over_cdp` 模式下会关闭用户正在用的 Chrome。脚本结束应只断开连接，不要调用 `browser.close()`。
- **浏览器可能被锁定**：TRAE 浏览器控制插件可能锁定 CDP 浏览器，抓取前确认 `http://127.0.0.1:9222/json/version` 可访问、页面可操作。

## 数据处理

- **去重必须按 aweme_id**：爬虫可能重复抓取。`crawl.py` 抓取完成后内建按 `aweme_id` 过滤去重，产出 `<root>/crawl_<account>/<account>_dedup.jsonl`，后续分析一律基于该去重稿，避免重复计数。
- **图文与视频区分**：`aweme_type == 68` 为图文，其余为视频。抽帧只对视频做，图文走拼图/切分流程。
- **数据完整性验证**：换新数据后，用脚本核对「新覆盖旧（按 aweme_id）」、字段空值、时间范围、类型分布，确认无遗漏再进入分析。
- **断点续传依赖产物存在性**：下载/抽帧/转写脚本均按「文件/记录已存在」跳过，因此换新数据时只需重跑一次，增量自动补齐（实测 162 条中仅重跑新增 105 条）。

## 内容分析

- **视觉分析必须真实**：对抽帧做真实视觉描述（格式/场景/人物/器物/构图/风格），缺失项用批量推理管线补齐。不得用推断冒充真实分析——报告页脚需注明"全部为真实视觉分析"。
- **BGM 分类不能假定存在独立音乐轨**：`music_download_url`/`published_audio_url` 是发布成片混合音轨，绝大多数情况下包含口播；报告应区分口播原声、混合音轨中的非口播证据和真正的歌曲识别，不要把混合音轨直接称为纯音乐或独立 BGM。
- **BGM 多为口播原声**（2026-08 实测）：45 首唯一音频中绝大多数转写文本与视频语音一致，说明账号几乎不依赖可独立分离的外部配乐。报告需如实说明，不要臆断"配乐策略"。
- **BGM 默认不加载模型**（2026-08）：BGM 复用已缓存的发布成片混合音轨，并按口播 transcript segments 排除语音窗口，只做剩余非口播区间的能量/低频/情绪启发式分析，避免无收益的二次 ASR。`--music-asr` 仅为兼容旧命令而保留，当前会被忽略并记录 `deprecated_ignored`；不能把口播转写冒充歌词。
- **BGM 归档是启发式、非曲目识别**（`tools/transcribe_bgm.py`）：默认用 PyAV 对排除口播后的非口播区间计算能量包络（低频占比判 BGM 强度 none/light/full）+ 启发式 mood；`--music-asr` 不再加载 large-v3，也不会对发布混合音轨重复 Whisper。强度阈值偏主观、未做音源去重与曲目比对，非口播证据不足时必须写 `unknown/证据不足`，报告须标注"描述性相关、非因果"。
- **`bgm_text` 默认始终为空**：不能拿口播 transcript 填充，也不能把混合音轨文本当歌词结论；当前 `--music-asr` 只记录请求状态 `deprecated_ignored`，如需真正歌曲识别必须另行设计独立音源和模型成本评估。
- **BGM×互动交叉揭示"该配的配到位"杠杆**（`tools/bgm_cross.py`，食品类账号实测）：轻 BGM 垫底内容的均赞约为纯口播的 **5.8×**、收藏约 15×、分享约 20×；情绪上"明快节奏"均赞约为"叙事起伏"的 5×，爆款 TOP10 大比例为明快节奏。账号整体 BGM 即使克制（本例七成纯干音），重点内容也会配轻 BGM + 明快节拍。**此数字取 `bgm/_cross.json`，报告勿手写。**
- **直播话术口音校对**（茶类目实测示例，方法通用）：主播方音导致大量误识别，按「误识别类型-出现场景-修正依据」对照表修正：
  - 产品名：某产品品牌名曾被误识别为 12 种同音近形变体
  - 工艺术语：如"窨制"→"印制"、"竹耙"→"猪八戒"、"提香"→"提交"
  - 原料名：如某原料名被误识为 3~4 种变体
  - 建立"误识别类型-出现场景-修正依据"对照表，确保术语修正准确

## 报告生成

- **图片用真实素材**：报告插图用视频抽帧/封面/图文图片，不用 AI 生成图（用户明确要求）。
- **章节结构**：对标报告标准章节为 账号定位 → 内容矩阵 → 文案写作逻辑 → 带货与变现逻辑 → 衰退归因 → TOP 素材拆解库 → 起号方案。
- **衰退归因辩证**：主页视频数据下降 ≠ 账号衰退。起号完成后战略重心转向直播变现，直播卖货数据持续递增——报告需区分"主页视频互动衰退"与"账号商业价值上升"。
- **报告必须基于全量数据**（2026-08 实测）：报告硬编码数字（总赞/均赞/分类条数/爆款榜/时间范围）必须与最新数据集一致。换新数据后，逐段核对封面、概览、趋势、分类、爆款拆解、对标基准、数据来源等所有硬编码文案，避免沿用旧样本数字。
- **HTML 验证**：修改报告后检查标签平衡、图片引用存在性，避免引入结构问题。
- **HTML 别"又杂又乱"——统一用 `render_report.py`**（2026-08 食品类账号重构沉淀）：报告 HTML 若手工/通用渲染器平铺，会出现长目录（27 项）刷屏、`#`/`## N *单位*` 数据卡被当普通标题、`>` 收治区无层次等杂乱。解药：技能内建 `tools/render_report.py`，**目录只收主章节 `## 01~07`**；`## 数据样本构成` 下的 `70 *条*`→ 数据样本大数字卡（`## 数字开头且非 01~07 序号`→卡，`## 01 章节`→section）；章内 `# 数字`→ 居中大数字卡，`# 口号/公式`→笔画强卡，`# 首行`→文档主标题；`>`→五类收治区自动着色；`--inline` 内联真实抽帧保单文件。**判定顺序反了会把 `## 01`~`07` 章节号误判成大数字卡，必须先用 `is_chapter_num`(1–2 位序号+汉字) 剔掉章节，再判 `is_datacard`(数字+量词/星号单位)。**（注：该经验适用于博主总结长文；对标报告 v2 已由 `report_html.py` 固定骨架直出，不再手写 HTML。）

## 评论抓取与拆解

- **评论抓取默认开启，每视频目标 100 条**：`crawl.py` 默认启用评论并设置 `MC_COMMENTS_COUNT=100`；只有明确不需要评论时传 `--no-comment`。评论落 `detail_comments_*.jsonl`，再用 `comments.py` 聚合并按赞保留每视频最多 100 条。若登录态或配置补丁不可用，必须报错，不得静默退回出厂 10 条。
- **评论 API 需登录态，但可复用**：MediaCrawler 在账号/单视频抓取完成、登录态仍在有效期时，`detail` 补抓评论会 CDP 自动拉起已登录 Edge，**无需重新扫码**，可串行多批抓完。每视频抓之间有 sleep 间隔，70 条视频全量约 30-40 分钟。
- **crawl.py 首次真实执行必现的 Popen bug**：`tee_run(a.mc_py, cmd, ...)` 误把**整个 cmd 数组**（含 `cmd[0]=python.exe`）当 main_args，tee_run 内部又前列插 `py` → 实际命令变成 `python.exe python.exe main.py ...`，解释器拿第一个 python.exe（PE 头 `MZ`）当脚本解析，报 `"File ...python.exe line 1 MZx" + source code cannot contain null bytes`。**修复：应传 `cmd[1:]`**。教训：凡封装脚本新增子进程调用，先核对 Popen 参数是否应从 `cmd[1:]` 起步。
- **勿用 `powershell -File` 拼中文路径做批处理**：代码页乱码会让 `Get-Content _batches.json` 路径失效，整个脚本第一句就报错退出（但进程 exit 0，极易被误判成功）。批处理循环一律用 **python 脚本 + `subprocess`** 驱动，中文路径天然安全。
- **`launch_type` 用 CDP 复用浏览器**：MediaCrawler 抖音走 CDP（`browser_data/cdp_dy_user_data_dir`，Edge + 调试端口 9222），抓取/补评论均沿用该登录态，勿另起 headless 新浏览器。

## 补丁与运行环境（2026-08-20 排障沉淀）

- **行内补丁正则禁用 `\s`，必须用 `[ \t]`**：`(?m)^VAR\s*=\s*\d+...\s*$` 里的 `\s` 会匹配换行——`CRAWLER_MAX_SLEEP_SEC = 2\n\n# 注释行` 会被 `\s*` 连吞两行再被 `(?:#.*)?` 吃掉注释行，150 行文件被替换成 148 行且丢失一行注释。历史事故：该 bug 使 sleep/comments 两个 env 补丁长期 `verify-failed`（被单行防护拦住没写盘），`MC_SLEEP_SEC`/`MC_COMMENTS_COUNT` 从未真正生效。修复：全部空白匹配改 `[ \t]`。
- **旧版无锚定 `\d+` 正则会污染整个 base_config.py**：曾把全文件所有数字字面量（`utf-8` 编码声明、版权年份、`9222` 端口、`START_PAGE=1`、注释里的行号）统统替换成 env 表达式，文件无法导入。三重防护：行首锚定 `(?m)^VAR`、`changed > 1` 即拒绝写盘、写后回读 marker 验证。
- **0.7.0 不依赖 `.bak` 恢复**：所有 `crawl.py` 注入都采用原子覆盖且不生成备份；版本门禁失败即停止，不写入不兼容的 MediaCrawler 源码。若需恢复，使用上游干净副本或重装 MediaCrawler，不读取或信任 `.bak`。
- **注入后的版本门禁必须复核**：在干净上游副本上验证 `MC_SLEEP_MIN/MC_SLEEP_MAX` 与 `MC_COMMENTS_COUNT` 的注入、导入和实际覆盖；门禁不通过就停止，不以放宽正则或继续运行代替修复。
- **`verify-failed` 返回值是防护生效的信号，不是误报**：见到它先复现替换过程逐步 diff（old/new 行数、差异行），不要简单放宽防护。
- **三方源码注入的当前规则**：0.7.0 的 `crawl.py` 只做原子覆盖、不生成 `.bak`；回滚统一使用上游干净副本/重装，版本门禁失败立即停止。
- **HTML 报告转义必须全覆盖并配 XSS 冒烟测试**：`report_html.py` 曾有 20+ 处动态文本裸拼（TOP 榜标题/关键帧图注/评论卡片与分组/BGM 标签情绪条/narrative 全部槽位/标题 kicker 副标题/pills/页脚附加）。规则：所有动态文本（数据源 + narrative 槽位）拼 HTML 前必须过 `esc()`；测试用 `<script>alert`、`<img onerror`、`<b>` 载荷分别注入 manifest 标题、评论内容、narrative intro，断言输出中只见转义后的实体。

## 统计正确性与空数据容错（2026-08-20 第二轮审计沉淀）

- **直方图分箱用左闭右开 `>=` / `<` 并与标签语义对齐**：旧版 `lk > bins[i] and lk <= bins[i+1]` 两个坑——0 赞视频所有条件皆假，落进 for-else 兜底档"10万+"；边界值（100/1k/1万）全部左错一档。分箱修复后必须用真实 manifest 点赞数逐档交叉验证（5 视频 5 档全对才算过）。
- **SVG `<title>`/`<text>` 内的动态标签也要 esc**：标签 `<100` 含裸 `<` 会破坏 SVG XML；HTML 容错解析下不报错但属无效标记，esc 后输出 `&lt;100`。
- **同一解析逻辑出现多处时必须共用同一个容错函数**：report_html 的 `_dt()` 有 try/except，但 TOP 榜渲染处裸调 `datetime.fromtimestamp(m['create_time'])`——`create_time=None`（process.py 无兜底透传）会让整份 882KB 报告在最后一步崩溃。修复：复用同款容错，坏值显示占位 `-`。
- **空数据是账号级聚合工具的必修课**：`max()` 空序列 ValueError、全 0 赞账号 `top1/total*100` 除零。account_metrics 现在三种前置校验：文件缺失/JSON 损坏/空 profiles 均 ap.error 友好退出；除零改 `if total else "0%"`。
- **所有落盘 JSON 一律原子写**：comments.json 曾直接 `json.dump(open(w))`，中断留半截 → decompose_prep 崩溃 + report_html 误报缺源。配套：读取侧（decompose_prep）也要 try/except 按缺源降级，双保险。
- **帧数不能冒充时长**：`duration_sec` 曾用 image_count 兜底，但 scene/intro 补帧会让帧数 > 秒数（虚高 10-30%），违背"禁止虚构"——缺源记 0。
- **`--fps 0` 类参数校验要在 argparse 后立即做**：除零异常会被 extract_frames 的 per-video except 吞掉，表现为视频静默 0 帧而非报错。
- **锁目录要检测 stale**：进程崩溃残留的 lock 目录会永久阻塞后续 Agent（30s 超时即退出）；按 mtime 判龄（10 分钟）接管删除。
- **probe 内存回退值方向要一致**：avail<=1GB 时回退 8 个 worker 与"内存越少越少 worker"语义相反，改回退 1（宁可慢）。
- **`frame.time or idx/rate` 是经典 falsy 陷阱**：PTS=0.0 是合法首帧时间戳，`or` 把 0 当缺失回退；显式 `is not None` 判断。
- **审计报告必须逐条源码复核再修**：子代理 35 项发现里 19 项是误报（如把 `one()` 内局部变量 `probs` 误读为全局、契约本就一致的 aid 映射、设计取舍当 bug）。修复前先读代码定位，避免反向引入问题。

## 逐帧分析性能与可观测性（2026-08-21 全流程实测沉淀）

- **逐帧分析必须进程池并行 + 断点续帧**：`analyze_frames.py` 旧版单进程逐帧串行，且每帧起一个 tesseract 子进程（每次冷启动加载 chi_sim+eng），实测约 2s/帧——14 视频 3559 帧需约 2 小时（上次回归 5 视频 628 帧约 21 分钟可交叉印证），百视频级账号将不可用。修复：帧间无共享状态，改 `multiprocessing.Pool`（按核数/内存封顶 8，每 worker 峰值约 0.5GB），实测 1032 帧 4 分钟（约 4.3 帧/s，提速 8.6×）；并按 `analysis in row` 跳过已完成帧，中断重跑只补增量。
- **子进程 print 默认块缓冲，重定向到日志文件时逐条进度全部不可见**：extract_frames/analyze_frames 的 `[i/14]` 输出直到进程退出才集中落盘，长时间阶段只剩 60s 心跳可看。规则：工具内所有进度 print 一律 `flush=True`（transcribe.py 已是惯例，其余工具对齐）。
- **OCR 语义不可因提速降级**：并行化只改执行结构（进程池映射），每帧仍全量 cv2 指标 + tesseract OCR，不做抽样——summary 的 subtitle/product 比例是全帧口径，抽样会让 frame_ratio 语义漂移。

## 增量重跑与静默降级（2026-08-21 48 条全量复测沉淀）

- **下载截断的 MP4 会以"静默 0 帧"穿透整条管线**：download.py 只校验最小字节数，截断文件照样 video_ok=True；PyAV 解码中途崩（`Invalid data found when processing input: avcodec_send_packet`），extract_frames 旧版把该视频按 0 帧返回且整体 exit 0，jpg 落一半、frames.json 缺失，下游 analyze_frames 直接跳过该视频——四层链路无一处报错。修复：extract() 解码失败返回 -1 与合法 0 帧区分，main 聚合失败清单并 `exit(1)` 附重下处置指引；处置流程为删损坏 MP4 → 重跑 download.py（断点只补缺）→ 重跑 extract_frames（其余视频 config 命中即跳过）。
- **bgm_cross 不能裸读 BGM 归档目录**：其自身产物 `_cross.json` 与 `_manifest.json` 同目录，重跑/增量跑时被当视频数据加载直接 `KeyError: aweme_id` 崩溃（首跑无此文件所以测试不出来）。规则：内部产物一律 `_` 前缀命名，读取侧统一 `startswith("_")` 跳过。
- **"lessons 已修复"≠全量修复**：v0.6.7 的 flush=True 只落在 analyze_frames.py，transcribe/transcribe_bgm/extract_frames/download 四个长时工具仍无 flush——后台重定向日志全程不可见直到进程退出，只能靠文件系统数产物监控。教训：横切型修复（flush/原子写/转义）落地后必须全目录扫一遍同类调用点，不能只修发现问题的那一个文件。
- **主页作品数核对已自动化**（v0.6.8）：save_creator 补丁落公开计数（aweme_count 等，无昵称隐私字段）到 `creator_profile.json`，crawl.py 抓后比对唯一视频数——未达 --max 上限即漏抓直接 exit(1)，达上限仍不足则提示调大重跑断点续传。此前"14/48 漏抓"正是 --max 裁剪 + 无核对静默放行所致。
- **评论"obtained"日志 ≠ 有评论**：MediaCrawler `get_comments` 对 0 评论视频同样打印 "comments have all been obtained"；请求裁剪应使用 MediaCrawler 作品元数据的 `comment_count=0`，覆盖完整性再用评论产物集合交叉核对（历史样本中 29 条零评论视频均为真实零评论，非漏抓）。
- **音频缓存必须按发布音轨统一复用**：`published_audio_url`（兼容 `music_download_url`/`music_url`/`audio_url`）对应发布成片混合音轨，按 URL hash 原子缓存到 `media-audio/<account>/published/<url_hash>.mp3`；口播 ASR 与 BGM 分析共享该文件。下载或解码失败才回退本地 MP4，最后回退 `speech_url` 远程视频。报告和 JSON 应保留实际来源、哈希、路径、`source_kind` 与回退原因。
- **口播转写应先快后精**：large-v3 首轮 `beam_size=1`，只对空段、低语言概率或低平均 logprob 音频重跑 `beam_size=5`；BGM 复用已有口播 transcript 排除语音窗口，默认不做二次 ASR，兼容参数 `--music-asr` 也会被忽略，避免无收益的显存和 token 消耗。
- **GPU 抽帧要真实落到解码/缩放链路**：NVDEC + `scale_cuda` 代理检测后，只提取候选高清帧；`--device auto|cuda|cpu`、180 帧软上限、感知/直方图去重和最短间隔共同防止帧数膨胀。GPU 单视频失败可回退 PyAV CPU，但 `frames.json` 必须写 `backend`/`fallback_reason`；损坏视频仍需 fail-loud。
- **阶段可乱序增量执行但要区分显卡资源**：口播转写完成后再启动抽帧/BGM 是默认调度；BGM 默认无 ASR，兼容参数 `--music-asr` 也会被忽略，因此可与 NVDEC 抽帧并行。各阶段断点配置包含输入与版本；`RunProgress` 的 `run-state.json` 同时记录阶段 `duration_sec` 和抓取优化吞吐。乱序执行后最后重跑各阶段补齐增量。

## 混合图文与抓取韧性（2026-08-21 89 条全量复测沉淀）

- **`aweme_type=68` 不能按视频处理**：混合主页中的图文没有可解码 MP4。manifest 必须保留作品类型与 `note_urls`，下载时把原图落到 `images/<account>/<aweme_id>/`，抽帧阶段再把原图导入统一 `frames.json` 契约；否则下载会伪报失败，视觉报告也会漏样本。
- **详情/评论的瞬时 Argus 拦截要在单请求层重试**：只重试整个 MediaCrawler 进程会重复已完成的大批请求。详情与评论单条 API 应指数退避重试并记录具体 `aweme_id`，最终仍由作品数和评论覆盖集合做质量门禁。
- **延时区间必须在每次请求时真正取样**：仅在进程启动时随机一次会让整轮请求保持固定节奏。使用 `uniform(sleep_min,sleep_max)` 逐请求取样，重试也重新取样。
- **短链接任务应优先复用已存在的 CDP 服务**：9222 已有 Edge 时直接连接；盲选下一个端口可能启动等待但无人登录。连接已有浏览器时只断开 CDP，不关闭用户浏览器。
- **dry-run 必须零副作用**：预览命令不能创建时间戳运行根、当前指针、账号绑定或锁目录，否则仅查看命令也会改变后续续跑选择。
- **Windows 子进程日志统一 UTF-8 与无缓冲**：`PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` + `PYTHONUNBUFFERED=1`，避免中文日志乱码并确保长任务进度及时可见。
- **音频 URL 要有结构化回退并留痕**：抓取层先兼容 `play_url.url_list`；manifest 保存 `published_audio_url`/兼容旧字段及视频 `speech_url`。口播优先走发布成片混合音轨，失败后走本地 MP4、再走远程视频；BGM 复用同一发布音轨并排除口播窗口，不把它写成独立纯 BGM。应记录 `source_kind`、URL hash、实际路径和 `fallback_reason`，这不是静默降级，报告和归档都能追溯实际音源。
- **详情/评论请求应按作品字段裁剪**：creator 详情已有完整字段时跳过 detail 请求；MediaCrawler 作品元数据明确 `comment_count=0` 的作品跳过评论请求；每次优化都通过 `saved_detail_requests`/`skipped_comment_requests` 计数并写入 `RunProgress`，不能用“评论 obtained”日志代替真实覆盖核验。
- **评论主题统计要与口径声明一致**：若报告声明“一条评论只计入首个命中主题”，实现必须按规则顺序命中后立即 `break`；对每个正则独立计数会让同一评论重复归类，主题占比总和失真。
- **BGM 交叉统计必须排除图文并校验集合完整性**：manifest 是全部作品，BGM 只适用于视频。直接以 manifest 总数作分母会把图文计入 `n`、压低所有占比；应先过滤 `aweme_type=68`，再校验每个视频都有 BGM 归档，缺源直接失败。
- **小倍数不能被低精度舍入成零**：轻 BGM 组可能远低于纯口播组，一位小数会把真实的非零比值显示为 `0.0`。交叉统计至少保留三位小数，并在日志中明确点赞、收藏、分享指标名。
- **结构自检通过不代表移动端无横向溢出**：长标题、表格最小内容宽度和多列网格会把页面撑出窄视口。报告交付前必须同时渲染桌面与移动截图；移动 CSS 要给网格使用 `minmax(0,1fr)`、长标题允许断行、表格局部横向滚动，并限制页面本身 `overflow-x`。
