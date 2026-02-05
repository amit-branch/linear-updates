from __future__ import annotations

from dataclasses import dataclass

import httpx


class OpenRouterError(RuntimeError):
    pass


@dataclass
class OpenRouterClient:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_s: float = 60.0
    provider: str | None = None  # e.g., "Cerebras" to prefer a specific provider

    def draft_markdown(self, facts: dict) -> str:
        system = (
            "You write concise weekly stakeholder updates in Markdown. "
            "Only use information provided. Do not invent progress. "
            "Structure by Project, then Last Week / This Week / Risks and Blockers within each. "
            "Never include ticket IDs. Keep wording action-oriented. "
            "Output ONLY the markdown, no explanations."
        )
        user = self._build_prompt(facts)
        content = self._chat(system=system, user=user, temperature=0.2)
        return self._extract_markdown(content or "")

    def _extract_markdown(self, content: str) -> str:
        """Extract only the markdown content, stripping any model thinking/reasoning."""
        # Look for the start of the actual markdown (# Weekly Update)
        import re

        match = re.search(r"^(# Weekly Update.*)", content, re.MULTILINE | re.DOTALL)
        if match:
            content = match.group(1)

        # Also strip any </think> or similar tags that might appear
        content = re.sub(r"</?\s*think\s*>", "", content, flags=re.IGNORECASE)

        return content.strip() + "\n"

    def _chat(self, *, system: str, user: str, temperature: float) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        # If using a model available on Cerebras, prefer Cerebras for speed
        if self.provider:
            body["provider"] = {"order": [self.provider]}

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                raise OpenRouterError(f"OpenRouter HTTP {resp.status_code}: {resp.text}")
            payload = resp.json()

        try:
            return payload["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise OpenRouterError(
                f"Unexpected OpenRouter response shape: {e}; payload keys={list(payload.keys())}"
            ) from e

    def _build_prompt(self, facts: dict) -> str:
        # Keep the prompt deterministic and structured; the model should output a markdown doc
        # with exactly two top-level sections: Last Week / This Week.
        team = facts["team"]["name"]
        prev = facts["previous_cycle"]
        curr = facts["current_cycle"]

        projects = facts["projects"]
        # Hard cap to avoid runaway prompt size; most recent comments already limited upstream.
        # If you hit this cap, consider reducing comment/history capture.
        import json

        raw = json.dumps(
            {
                "team": team,
                "previous_cycle": prev,
                "current_cycle": curr,
                "projects": projects,
            },
            ensure_ascii=False,
            indent=2,
        )
        if len(raw) > 160_000:
            raw = raw[:159_000] + "\n…(truncated)\n"

        return f"""Write a weekly stakeholder update in Markdown for team: {team}.

Requirements:
- Output Markdown only. Do NOT include ticket IDs (like LP-123) - stakeholders don't need them.
- Use this exact structure for EACH project:
  ## Project Name
  **Last Week**
  - bullet points...
  **This Week**
  - bullet points...
  **Risks and Blockers** (only if there are blocked or stale issues for this project)
  - bullet points...
- "Last Week" = completed cycle. Use past tense: "Completed X", "Fixed Y", "Released Z".
- "This Week" = current/ongoing cycle. Use present/future tense: "Working on X", "In progress".
  Even if an issue shows "Done", frame it as planned work, NOT as completed.
- "Risks and Blockers" = issues where is_blocked=true or is_stale=true for that project.
  For blocked: Explain WHY it's blocked and what's the latest update to resolve it (from comments).
  For stale (idle >2 weeks): Explain why idle, or just note it's been pending for weeks.
  Focus on actionable context, not ticket details.
  Omit this section entirely if a project has no blocked/stale issues.
- Do not mention internal implementation details or ticket IDs.
- Prefer concise bullets. If nothing noteworthy for Last Week or This Week, say "No updates".

Facts (JSON):
```json
{raw}
```
"""
