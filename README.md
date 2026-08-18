# douyin-crawl-report

> 抖音账号视频抓取 + 对标分析报告生成 · Agent Skill 一站式方案

把「深挖一个抖音账号」从几小时的苦力活，变成几分钟的自动化流水线。**抓取 → 去重 → 视觉/BGM/话术分析 → 对标报告**，全链路落地，开箱即用。

[![Skill](https://img.shields.io/badge/Type-Agent%20Skill-blue.svg)](./SKILL.md)
[![Version](https://img.shields.io/badge/Version-0.1.0-brightgreen.svg)](./manifest.json)
[![License](https://img.shields.io/badge/License-MIT-orange.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/Status-Reusable-success.svg)](./manifest.json)

---

## 为什么用它

做电商、做内容、做竞品研究的同学都绕不开一件事：**想知道某个对标账号是怎么火的**。但它通常意味着：

- ❌ 手工一条条录数据、记标题、记点赞，几天才能攒个全量样本
- ❌ 看视频要逐条听口播、扒话术，纯靠人耳整理
- ❌ 最后只能凭感觉总结「TA 的内容很牛」，说不出到底赢在哪

这个技能把这些全部自动化，产出一份**基于全量真实数据**的对标分析报告，让「抄作业」变得有据可依。

---

## 核心能力

| 环节 | 能力 | 亮点 |
|------|------|------|
| 抓取 | 单视频 / 整账号批量 | 断点续传 + 8–10s 智能间隔，破风控不封号 |
| 破解 | 浏览器内 `fetch` 直连 API | 复用浏览器自身 `a_bogus` 签名，一次抓全 9 页 162 条 |
| 处理 | 去重 / 下载 / 图文切分 | 按 `aweme_id` 增量更新，只跑新增数据 |
| 转写 | 口播 + BGM 分离转写 | 多进程并行，口播 medium + 6 worker 提速约 5× |
| 分析 | 抽帧视觉 / 话术 / 主题矩阵 | 真实抽帧，人工校对口音误识（如 镁钙D→美加D） |
| 报告 | 逐视频 + 全量对标 | 定位 / 内容矩阵 / 带货逻辑 / 爆款拆解 / 起号方案 |

---

## 实战战绩（2026-08 已跑通）

> 在「斗茶谷安安」茶类账号跑通全量 162 条深度分析，已沉淀进 `LESSONS/实战优化` 与 `references/workflow.md`。

- ⚡ **抓取提速一个数量级**：签名失效时改用浏览器 `fetch` 直连，一次抓全，不再逐条重试
- ⚡ **9 页 162 条数据**：分页参数补全（`from_user_page`、`need_time_list` 等），杜绝「看似到底实则漏抓」
- ⚡ **转写 21 分钟搞定**：多进程 + 增量管线，162 条仅重跑新增部分
- ✅ **600% 漏抓预警**：必须与主页显示数核对，曾只抓到 57/162 即被标记
- ✅ **转写成功率 100%**：error 自动补转，报告前强制 0 失败
- ✅ **报告数据零陈旧**：所有硬编码数字（总赞/均赞/爆款榜）与最新数据集强一致

---

## 快速开始

### 1. 装载技能

把本仓库作为 Agent Skill 安装到你的技能目录，通过 `SKILL.md` 触发。

### 2. 触发场景

```text
/抓取我的对标账号：https://v.douyin.com/xxxxxx
```

| 输入 | 输出 |
|------|------|
| 账号主页 URL | 批量抓取全部视频 → 对标分析报告 |
| 单视频 URL | 抓取单条 → 逐视频报告 |
| 指定已抓取数据分析 | 对标报告（定位/矩阵/爆款/起号方案） |

### 3. 产出清单

```text
data/douyin/jsonl/*_dedup.jsonl    # 去重元数据
videos/                            # 无水印视频 + 封面
data/douyin/frames/                # 抽帧视觉素材
per-video-breakdown.html           # 逐视频拆解
douyin-tea-benchmark.html          # 全量对标报告
```

---

## 完整工作流

```
抓取 ─► 数据处理 ─► 内容分析 ─► 报告生成
 │        │           │            │
 │  detail 单条      去重       抽帧视觉      逐视频报告
 │  creator 批量     下载视频   BGM 转写      对标分析报告
 └ 断点续传/间隔    图文切分   话术校对口音   定位/矩阵/爆款
```

- 详细步骤 → [`references/workflow.md`](./references/workflow.md)
- 命令清单 → [`references/commands.md`](./references/commands.md)
- 踩坑经验 → [`references/lessons-learned.md`](./references/lessons-learned.md)

---

## 为什么这个 Skill 够「懂事」

它不是一坨提示词，而是带**治理层**的工程化技能包：

- **四阶段管线**：抓取 → 处理 → 分析 → 报告，每阶段可断点续作
- **质量护栏**：内置 `output-risk-profile` / `artifact-design-profile` 等质量门
- **系统模型**：`system-model.md` 给出边界、反馈回路、失败地图与杠杆点
- **双语文档**：`skill-interpretation.html` / `skill-overview.html` 中英一键切换
- **持续反哺**：每次实战踩坑都回写 `lessons-learned.md`，越用越准

```
reports/
├─ intent-dialogue.md        需求澄清起点
├─ skill-interpretation.html 双语解读报告
├─ skill-overview.html       技能审计报告
├─ review-studio.html        评审工作台
├─ output-risk-profile.md    失败模式与自检
└─ system-model.md           系统思考模型
```

---

## 合规声明

- 仅抓取**公开信息**，遵守抖音平台规则与法律边界
- 不做平台逆向，不做大规模爬虫
- 视觉分析基于真实抽帧，不推断冒充

---

## LICENSE

[MIT](./LICENSE)

---

<p align="center">
  📦 一个 Skill，挖透一个账号 · <b>数据驱动对标，拒绝拍脑袋</b>
</p>