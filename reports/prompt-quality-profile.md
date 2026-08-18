# Prompt Quality Profile

Skill: `douyin-crawl-report`
Relevance: `prompt-heavy`
Overall quality score: `90.0/100`

## Primary Task Family

**Creative generation**
- Matched keywords: copy, content, 内容

## Complexity

- Band: `expert`
- Score: `10`
- Reason: multiple task families plus governance, evaluation, or expert-level constraints

## Need Model

- Explicit Need: 从抖音账号URL或视频URL抓取视频数据（单个视频detail模式+批量creator模式），处理数据后生成对标分析报告
- Implicit Need: The reusable skill needs a stable role, task, and output contract rather than a one-off prompt.
- Scenario: 抖音账号主页URL（https://www.douyin.com/user/{sec_uid}）用于批量抓取全部视频；或单个视频URL（https://www.douyin.com/video/{aweme_id}）用于抓取单条视频
- User Level: infer from examples and standards; ask only if it changes output depth
- Success Standard: 数据完整性(覆盖全部视频)、去重无遗漏、报告含真实视觉分析而非推断、章节结构完整

## RTF To Skill Mapping

- Role: Use a taste-aware creator role with clear audience, tone, and originality boundaries.
- Task: Generate variants, explain selection logic, and preserve the user's distinctive constraints.
- Format: Return options with rationale, selection criteria, and refinement paths.

## Quality Matrix

### Completeness — 100/100
- Matched signals: input, output, constraint, example
- Repair: Name missing inputs, outputs, constraints, or success standards before deepening the package.

### Clarity — 90/100
- Matched signals: clear, specific
- Repair: Replace broad verbs with observable actions and define what done means.

### Consistency — 85/100
- Matched signals: boundary
- Repair: Check that role, task, format, exclusions, and examples do not contradict each other.

### Practicality — 95/100
- Matched signals: execute, use, workflow
- Repair: Add runnable steps, examples, or verification cues instead of abstract advice.

### Specificity — 80/100
- Matched signals: none
- Repair: Anchor wording in the user's audience, domain nouns, and target outcome.

## Matched Task Families

### Creative generation
- Score: `3`
- Keywords: copy, content, 内容
- Role: Use a taste-aware creator role with clear audience, tone, and originality boundaries.
- Task: Generate variants, explain selection logic, and preserve the user's distinctive constraints.
- Format: Return options with rationale, selection criteria, and refinement paths.

### Prompt engineering
- Score: `3`
- Keywords: prompt, role, format
- Role: Use a prompt engineer role only when role design materially improves execution.
- Task: Map Role, Task, and Format into skill behavior rather than copying a large prompt template.
- Format: Return a compact prompt contract plus tests, quality matrix, and usage notes.

### Analytical reasoning
- Score: `2`
- Keywords: analysis, 分析
- Role: Use an analyst role that separates evidence, inference, uncertainty, and recommendation.
- Task: State assumptions, compare alternatives, and make the decision path inspectable.
- Format: Return findings, evidence, tradeoffs, recommendation, and residual risks.

### Execution operation
- Score: `2`
- Keywords: workflow, execute
- Role: Use an operator role with explicit boundaries, inputs, outputs, and failure handling.
- Task: Convert the job into ordered steps with validation checks and stop conditions.
- Format: Return a runbook-like handoff with commands, checks, owners, and next actions when relevant.

## Self-Repair Checks

- Check explicit need, implicit need, scenario, user level, and success standard before deepening.
- Map Role, Task, and Format into skill behavior, not decorative prompt labels.
- Ask one focused clarification only when missing information changes the package boundary.
- Add tests or examples for prompt-heavy behavior before treating it as reusable.
- Keep prompt methodology in references and reports instead of bloating SKILL.md.

## Reviewer Note

Use this profile when the package depends on prompt behavior, role design, output contracts, or conversation quality.
