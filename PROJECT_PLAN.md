# Project Plan: Linear Weekly Stakeholder Updates

## Objective

CLI automation that reads Linear **Projects** and their **Issues** for:
- **Previous Cycle** → "Last Week"
- **Current Cycle** → "This Week"

…then drafts a stakeholder-ready weekly update using an OpenRouter LLM and either:
- Writes to `updates/weekly_update.md`, or
- Posts directly to Linear as Project Updates

## Scope Rules

- Report at the **project level** only.
- Ignore issues that are not linked to any project.
- Include only projects whose status is one of:
  `Evaluation`, `PRD`, `Design`, `Development`, `QA`, `Ready for Release`, `Limited Release`.

## Data Collection (Linear GraphQL)

1. Identify the team (via `LINEAR_TEAM_ID` or `LINEAR_TEAM_KEY`).
2. Fetch cycles and determine:
   - Current cycle (contains "now"; fallback to next future cycle)
   - Previous cycle (immediately preceding)
3. Fetch all projects visible to the team; filter to allowed statuses.
4. For each in-scope project:
   - Fetch issues in the **Previous Cycle**
   - Fetch issues in the **Current Cycle**
5. For Previous Cycle issues: collect comments and state changes within the cycle window.
6. For Current Cycle issues: collect comments, state changes, and identify blocked/stale issues.

## Drafting (OpenRouter)

- Model: `OPENROUTER_MODEL` (default `openai/gpt-oss-120b`)
- Provider: `OPENROUTER_PROVIDER` (optional, e.g., `Cerebras` for fast inference)
- Output format (per project):
  ```
  ## Project Name
  **Last Week**
  - bullet points (past tense)
  **This Week**
  - bullet points (present/future tense)
  **Risks and Blockers** (only if applicable)
  - blocked issues with context
  - stale issues (idle >2 weeks)
  ```
- Content rules:
  - "Last Week" uses past tense, derived from Previous Cycle history + comments.
  - "This Week" uses present/future tense, even for completed items in Current Cycle.
  - "Risks and Blockers" explains why issues are blocked/stale and latest resolution efforts.
  - No ticket IDs in output (stakeholders don't need them).

## Output

- Overwrites `updates/weekly_update.md` on every run (atomic replace).
- Optional: write raw facts JSON for debugging (`--save-raw`).
- Optional: post each project's update directly to Linear Project Updates.

## CLI Commands

| Command | Description |
|---------|-------------|
| `linear-updates validate` | Check team/cycles/projects visibility |
| `linear-updates draft` | Generate and write markdown locally |
| `linear-updates draft --no-llm` | Produce fact-only markdown (no LLM call) |
| `linear-updates draft --dry-run` | Print to stdout without writing file |
| `linear-updates post-to-linear` | Generate update and post to Linear |
| `linear-updates post-to-linear --dry-run` | Preview what would be posted |

All commands show a progress spinner while fetching data.

## Scheduling

Run weekly on **Mondays 5:00 PM IST** via crontab:
```
30 11 * * 1 cd /path/to/linear_updates && uv run linear-updates post-to-linear
```

## Status

### Completed
- [x] CLI + Linear fetch + facts + LLM draft + markdown output
- [x] Project-first output structure (Last Week / This Week per project)
- [x] Risks and Blockers section for blocked/stale issues
- [x] Comments used for context in both cycles
- [x] Progress indicator with spinner
- [x] Post updates directly to Linear via `projectUpdateCreate` mutation
- [x] Preserve existing project health status when posting

### Future Enhancements
- [ ] Retry/backoff on API calls
- [ ] Historical tracking (dated output files)
- [ ] Slack/email integration
- [ ] Unit tests for cycle selection/time window filtering
