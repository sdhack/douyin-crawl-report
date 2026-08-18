# Iteration Directions

Skill: `douyin-crawl-report`

- Maturity tier: `production`
- Selection rule: Pick the three smallest next steps that increase reliability more than they increase context cost.
- Start here: `Tighten trigger and exclusions`
- Why first: The package needs clearer near-neighbor exclusions before it grows.
- Defer for now: `Deepen operator guidance`

## Top 3 Next Moves

### 1. Tighten trigger and exclusions

- Why now: The package needs clearer near-neighbor exclusions before it grows.
- Timing: Do this first.
- Recommended actions:
  - Add 3 to 5 should-trigger and should-not-trigger examples.
- Unlocks: Cleaner routing and fewer accidental activations.
- Wait on: Wait to add broader structure until this move clearly improves reliability.

  - Refine the frontmatter description to name the recurring job and non-goals.
- Unlocks: Cleaner routing and fewer accidental activations.
- Wait on: Wait to add broader structure until this move clearly improves reliability.

  - Run a first trigger evaluation pass before expanding the package.
- Unlocks: Cleaner routing and fewer accidental activations.
- Wait on: Wait to add broader structure until this move clearly improves reliability.

### 2. Add the first execution asset

- Why now: The package is still mostly prose. Add one asset that removes repeated manual work.
- Timing: Do this after the first move lands cleanly.
- Recommended actions:
  - Move stable procedural guidance into references if users will need it repeatedly.
- Unlocks: Stronger execution quality without bloating the entrypoint.
- Wait on: Wait until the package has evidence that this extra structure is justified.

  - Create one deterministic helper script if a repeated step can be executed instead of described.
- Unlocks: Stronger execution quality without bloating the entrypoint.
- Wait on: Wait until the package has evidence that this extra structure is justified.

  - Keep the main SKILL.md compact and route-oriented.
- Unlocks: Stronger execution quality without bloating the entrypoint.
- Wait on: Wait until the package has evidence that this extra structure is justified.

### 4. Deepen operator guidance

- Why now: The workflow is still thin and may not be repeatable by another operator.
- Timing: Do this after the first move lands cleanly.
- Recommended actions:
  - Split the job into distinct phases or checkpoints.
- Unlocks: Better repeatability and easier human review.
- Wait on: Wait until the package has evidence that this extra structure is justified.

  - Add success conditions and failure boundaries for each phase.
- Unlocks: Better repeatability and easier human review.
- Wait on: Wait until the package has evidence that this extra structure is justified.

  - Link outputs to the step that produces them.
- Unlocks: Better repeatability and easier human review.
- Wait on: Wait until the package has evidence that this extra structure is justified.
