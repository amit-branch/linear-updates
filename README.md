# Linear Weekly Updates

Generate and post weekly stakeholder updates from Linear projects.

## Initial Setup (One-time)

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install dependencies

Unzip the project, then:

```bash
cd linear_updates
uv sync
```

### 3. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```
LINEAR_API_KEY=lin_api_xxxxx        # From Linear Settings → API
OPENROUTER_API_KEY=sk-or-xxxxx      # From openrouter.ai
```

> **Note:** To post updates to Linear, your Linear API key needs **read & write** access.

## Configuration (Optional)

You can customize the LLM model and provider in `.env`:

```
OPENROUTER_MODEL=openai/gpt-oss-120b     # Default model
OPENROUTER_PROVIDER=Cerebras             # Fast inference provider
```

**To use a different model:** Change `OPENROUTER_MODEL` to any model from [openrouter.ai/models](https://openrouter.ai/models).

**To use the default provider:** Leave `OPENROUTER_PROVIDER` empty or remove the line entirely. OpenRouter will automatically pick the best available provider.

## Commands

### Post updates to Linear

Generates the weekly update and posts it to each project in Linear:

```bash
uv run linear-updates post-to-linear
```

### Preview without posting

See what would be posted without actually posting:

```bash
uv run linear-updates post-to-linear --dry-run
```

### Generate markdown only

Write the update to a local file without posting to Linear:

```bash
uv run linear-updates draft
```

## Output

- Updates are saved to `updates/weekly_update.md`
- Each project gets its own update posted to Linear's Project Updates section

## Scheduling (Optional)

To run automatically every Monday at 5 PM IST:

```bash
crontab -e
```

Add this line (replace paths with your actual paths):

```
30 11 * * 1 cd /Users/yourname/linear_updates && ~/.local/bin/uv run linear-updates post-to-linear >> /tmp/linear-updates.log 2>&1
```

> **Note:** 5 PM IST = 11:30 AM UTC. The `30 11 * * 1` means "11:30 AM UTC every Monday".
