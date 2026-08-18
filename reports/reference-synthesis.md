# Reference Synthesis

Skill: `douyin-crawl-report`
- Description: 从抖音账号/视频 URL 抓取视频数据（单个+批量），经数据处理、视觉/BGM/话术分析后生成对标分析报告。Invoke when user wants to crawl a Douyin creator's videos by account URL and produce an analysis report.
- Intent confidence: `95/100` (`high`)

## Live GitHub Benchmarks

- No live GitHub benchmarks are attached yet.

## Curated World-Class Pattern Tracks

### Official skill anatomy and context discipline
- Type: `official`
- Evidence mode: `curated-pattern-track`
- Why relevant: This track matches: general fit.
- Borrow: Borrow progressive disclosure: keep the entrypoint lean and move depth into references or scripts.
- Avoid: Do not let packaging or platform concerns swallow the core job boundary.

### Hypothesis-test-learn loop
- Type: `research`
- Evidence mode: `curated-pattern-track`
- Why relevant: This track matches: benchmark.
- Borrow: Borrow a small hypothesis-test-learn loop so the first revision is evidence-backed.
- Avoid: Do not create experimental overhead that exceeds the skill's real risk tier.

### Outcome-backwards design
- Type: `principles`
- Evidence mode: `curated-pattern-track`
- Why relevant: This track matches: output.
- Borrow: Borrow the habit of designing from the required hand-back output backwards.
- Avoid: Do not start with architecture terms before the deliverable is concrete.

## Borrow Now

- Borrow progressive disclosure: keep the entrypoint lean and move depth into references or scripts.
- Borrow a small hypothesis-test-learn loop so the first revision is evidence-backed.
- Borrow the habit of designing from the required hand-back output backwards.

## Avoid Now

- Do not let packaging or platform concerns swallow the core job boundary.
- Do not create experimental overhead that exceeds the skill's real risk tier.
- Do not start with architecture terms before the deliverable is concrete.

## Pattern Gate

- Summary: 3 accepted, 0 deferred using threshold 3/4.
- Acceptance threshold: `3/4`
- Accepted patterns:
  - **Official skill anatomy and context discipline**: 3/4 (recurrence, generativity, boundary)
  - **Hypothesis-test-learn loop**: 4/4 (recurrence, generativity, distinctiveness, boundary)
  - **Outcome-backwards design**: 4/4 (recurrence, generativity, distinctiveness, boundary)

## Default Recommendation

- Summary: Start by borrowing this pattern: Borrow progressive disclosure: keep the entrypoint lean and move depth into references or scripts. Avoid this for the first pass: Do not let packaging or platform concerns swallow the core job boundary.
- Why: There is a real design conflict to resolve: The stated preference leans lightweight or speed-first, while the benchmark mix leans toward governance, review, or heavier evaluation structure.
- User decision required: `True`

## Visibility Mode

- Mode: `explicit`
- Reasons: design_conflict
- User note: Surface the recommendation because intent is still settling or there is a real design conflict that needs a user call.
- Reviewer note: Keep the full benchmark and synthesis evidence visible for authors and reviewers.

## Conflict Check

- **lightweight_vs_governance**: The stated preference leans lightweight or speed-first, while the benchmark mix leans toward governance, review, or heavier evaluation structure.

## Quality Lift Thesis

- Use GitHub repositories for concrete package and workflow patterns.
- Use curated official or commercial tracks for entrypoint and operator ergonomics.
- Use research tracks to justify the smallest evaluation loop that still catches regressions.
- Use principle tracks to keep the package small, boundary-aware, and outcome-driven.

## Decision Prompt

Use the recommendation by default. Only surface the underlying benchmark tradeoffs when intent is uncertain or a real design conflict needs a deliberate call.
