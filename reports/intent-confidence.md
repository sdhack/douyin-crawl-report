# Intent Confidence

- Confidence score: `95/100`
- Confidence band: `high`
- Gate passed: `True`
- Recommended action: Intent is clear enough to package the first routeable version.

## Current Reading

从抖音账号URL或视频URL抓取视频数据（单个视频detail模式+批量creator模式），处理数据后生成对标分析报告 Primary output: 1) data/douyin/jsonl/ 下的JSONL原始数据（去重后）；2) 逐视频分析报告 per-video-breakdown.html（含视觉描述/BGM/互动数据）；3) 对标分析报告 douyin-tea-benchmark.html（含账号定位/内容矩阵/带货逻辑/素材拆解/起号方案）. Exclusions: 不做平台逆向、不做大规模爬虫、不生成AI图片、不修改抓取到的原始数据.

## Strong Signals

- The recurring job is concrete enough to anchor the package.
- Real input shape is explicit.
- The hand-back output is concrete.
- Boundary exclusions are already explicit.
- Operational constraints are visible.

## Gaps To Close

- No major intent gaps detected.

## Follow-Up Questions

- No extra follow-up questions required before the first package.
