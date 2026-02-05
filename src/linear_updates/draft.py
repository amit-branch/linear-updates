from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import AppConfig
from .linear_client import LinearAPIError, LinearClient
from .models import Cycle, Team
from .openrouter_client import OpenRouterClient

ALLOWED_PROJECT_STATUSES = {
    "Evaluation",
    "PRD",
    "Design",
    "Development",
    "QA",
    "Ready for Release",
    "Limited Release",
}


def _pick_team(client: LinearClient, config: AppConfig) -> Team:
    teams = client.list_teams()
    if config.team_id:
        for t in teams:
            if t.id == config.team_id:
                return t
        raise LinearAPIError(f"LINEAR_TEAM_ID not found or not accessible: {config.team_id}")

    if config.team_key:
        for t in teams:
            if (t.key or "").lower() == config.team_key.lower():
                return t
        raise LinearAPIError(f"LINEAR_TEAM_KEY not found or not accessible: {config.team_key}")

    if len(teams) == 1:
        return teams[0]

    raise LinearAPIError(
        "Multiple teams accessible; set LINEAR_TEAM_ID or LINEAR_TEAM_KEY. "
        f"Accessible teams: {', '.join([f'{t.name}({t.key or t.id})' for t in teams])}"
    )


def _pick_cycles(cycles: list[Cycle], now_utc: datetime) -> tuple[Cycle, Cycle]:
    cycles_sorted = sorted(cycles, key=lambda c: c.starts_at)
    current = next((c for c in cycles_sorted if c.starts_at <= now_utc <= c.ends_at), None)

    if current is None:
        future = [c for c in cycles_sorted if c.starts_at > now_utc]
        past = [c for c in cycles_sorted if c.ends_at <= now_utc]
        if future and past:
            current = min(future, key=lambda c: c.starts_at)
            previous = max(past, key=lambda c: c.ends_at)
            return current, previous
        raise LinearAPIError("Could not determine current/previous cycle from available cycles.")

    previous_candidates = [c for c in cycles_sorted if c.ends_at < current.starts_at]
    if not previous_candidates:
        raise LinearAPIError("Found current cycle but no previous cycle was available.")
    previous = max(previous_candidates, key=lambda c: c.ends_at)
    return current, previous


def validate_access(config: AppConfig) -> dict:
    client = LinearClient(api_key=config.linear_api_key)
    team = _pick_team(client, config)
    cycles = client.list_team_cycles(team.id)
    now_utc = datetime.now(UTC)
    current, previous = _pick_cycles(cycles, now_utc)
    projects = client.list_team_projects(team.id)
    allowed = [p for p in projects if (p.status_name or "") in ALLOWED_PROJECT_STATUSES]

    return {
        "team": asdict(team),
        "now_utc": now_utc.isoformat(),
        "current_cycle": {
            "id": current.id,
            "name": current.name,
            "number": current.number,
            "starts_at": current.starts_at.isoformat(),
            "ends_at": current.ends_at.isoformat(),
        },
        "previous_cycle": {
            "id": previous.id,
            "name": previous.name,
            "number": previous.number,
            "starts_at": previous.starts_at.isoformat(),
            "ends_at": previous.ends_at.isoformat(),
        },
        "projects_visible": len(projects),
        "projects_in_scope": len(allowed),
    }


def draft_weekly_update(
    *, config: AppConfig, use_llm: bool, on_progress: Callable[[str], None] | None = None
) -> tuple[str, dict]:
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    client = LinearClient(api_key=config.linear_api_key)
    progress("Connecting to Linear...")
    team = _pick_team(client, config)

    now_utc = datetime.now(UTC)
    progress(f"Fetching cycles for {team.name}...")
    cycles = client.list_team_cycles(team.id)
    current_cycle, previous_cycle = _pick_cycles(cycles, now_utc)

    progress("Fetching projects...")
    projects = client.list_team_projects(team.id)
    projects_in_scope = [p for p in projects if (p.status_name or "") in ALLOWED_PROJECT_STATUSES]
    projects_in_scope.sort(key=lambda p: (p.status_name or "", p.name.lower()))

    prev_start = previous_cycle.starts_at
    prev_end = previous_cycle.ends_at

    project_facts: list[dict] = []
    for i, project in enumerate(projects_in_scope, 1):
        progress(f"Fetching issues for {project.name} ({i}/{len(projects_in_scope)})...")
        prev_issues = client.list_issues_for_project_cycle(
            project_id=project.id, cycle_id=previous_cycle.id
        )
        curr_issues = client.list_issues_for_project_cycle(
            project_id=project.id, cycle_id=current_cycle.id
        )

        prev_issue_facts: list[dict] = []
        for issue in prev_issues:
            comments = client.list_issue_comments(issue.id)
            history = client.list_issue_history(issue.id)

            comments_in_window = [
                {
                    "created_at": c.created_at.isoformat(),
                    "author": c.author_name,
                    "body": _truncate(c.body, 500),
                }
                for c in comments
                if prev_start <= c.created_at <= prev_end
            ]
            history_in_window = [
                {
                    "created_at": h.created_at.isoformat(),
                    "type": h.type,
                    "from_state": h.from_state,
                    "to_state": h.to_state,
                }
                for h in history
                if prev_start <= h.created_at <= prev_end
            ]

            prev_issue_facts.append(
                {
                    "id": issue.id,
                    "key": issue.identifier,
                    "title": issue.title,
                    "url": issue.url,
                    "state": issue.state_name,
                    "assignee": issue.assignee_name,
                    "history": history_in_window,
                    "comments": comments_in_window[-5:],  # keep the most recent ones in-window
                }
            )

        curr_start = current_cycle.starts_at
        curr_end = current_cycle.ends_at
        two_weeks_ago = now_utc - timedelta(weeks=2)

        curr_issue_facts: list[dict] = []
        for issue in curr_issues:
            comments = client.list_issue_comments(issue.id)
            history = client.list_issue_history(issue.id)

            # Comments within cycle window for regular updates
            comments_in_window = [
                {
                    "created_at": c.created_at.isoformat(),
                    "author": c.author_name,
                    "body": _truncate(c.body, 500),
                }
                for c in comments
                if curr_start <= c.created_at <= curr_end
            ]

            # Latest 3 comments regardless of window (for blockers context)
            latest_comments = [
                {
                    "created_at": c.created_at.isoformat(),
                    "author": c.author_name,
                    "body": _truncate(c.body, 500),
                }
                for c in sorted(comments, key=lambda x: x.created_at, reverse=True)[:3]
            ]

            # Find when state last changed
            state_changes = [h for h in history if h.to_state is not None]
            last_state_change = max(
                (h.created_at for h in state_changes), default=None
            )
            is_stale = last_state_change is not None and last_state_change < two_weeks_ago
            is_blocked = (issue.state_name or "").lower() == "blocked"

            curr_issue_facts.append(
                {
                    "id": issue.id,
                    "key": issue.identifier,
                    "title": issue.title,
                    "url": issue.url,
                    "state": issue.state_name,
                    "assignee": issue.assignee_name,
                    "comments": comments_in_window[-5:],
                    "latest_comments": latest_comments,
                    "last_state_change": (
                        last_state_change.isoformat() if last_state_change else None
                    ),
                    "is_blocked": is_blocked,
                    "is_stale": is_stale,
                }
            )

        project_facts.append(
            {
                "id": project.id,
                "name": project.name,
                "url": project.url,
                "status": project.status_name,
                "last_week": {
                    "cycle_id": previous_cycle.id,
                    "cycle_name": previous_cycle.name,
                    "cycle_number": previous_cycle.number,
                    "window_start": prev_start.isoformat(),
                    "window_end": prev_end.isoformat(),
                    "issues": prev_issue_facts,
                },
                "this_week": {
                    "cycle_id": current_cycle.id,
                    "cycle_name": current_cycle.name,
                    "cycle_number": current_cycle.number,
                    "issues": curr_issue_facts,
                },
            }
        )

    facts: dict = {
        "generated_at_utc": now_utc.isoformat(),
        "team": asdict(team),
        "current_cycle": {
            "id": current_cycle.id,
            "name": current_cycle.name,
            "number": current_cycle.number,
            "starts_at": current_cycle.starts_at.isoformat(),
            "ends_at": current_cycle.ends_at.isoformat(),
        },
        "previous_cycle": {
            "id": previous_cycle.id,
            "name": previous_cycle.name,
            "number": previous_cycle.number,
            "starts_at": previous_cycle.starts_at.isoformat(),
            "ends_at": previous_cycle.ends_at.isoformat(),
        },
        "projects": project_facts,
    }

    if use_llm:
        if not config.openrouter_api_key:
            raise ValueError("Missing OPENROUTER_API_KEY (or run with --no-llm).")
        progress("Generating update with LLM...")
        llm = OpenRouterClient(
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
            provider=config.openrouter_provider,
        )
        markdown = llm.draft_markdown(facts)
    else:
        progress("Generating markdown...")
        markdown = _facts_to_markdown(facts)

    return markdown, facts


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _facts_to_markdown(facts: dict) -> str:
    tz = ZoneInfo("Asia/Kolkata")

    def _fmt(dt_iso: str) -> str:
        return datetime.fromisoformat(dt_iso).astimezone(tz).strftime("%Y-%m-%d %H:%M IST")

    lines: list[str] = []
    lines.append(f"# Weekly Update ({facts['team']['name']})")
    lines.append("")
    lines.append(f"Generated: {_fmt(facts['generated_at_utc'])}")
    lines.append("")

    for p in facts["projects"]:
        lines.append(f"## {p['name']}")
        if p.get("url"):
            lines.append(f"*{p.get('status') or 'Unknown'}* — [Project Link]({p['url']})")
        else:
            lines.append(f"*{p.get('status') or 'Unknown'}*")
        lines.append("")

        lines.append("**Last Week**")
        last_issues = p["last_week"]["issues"]
        if not last_issues:
            lines.append("- No updates")
        else:
            for i in last_issues:
                key = i.get("key") or "ISSUE"
                state = i.get("state") or "Unknown"
                assignee = i.get("assignee") or "Unassigned"
                title = i.get("title")
                lines.append(f"- {key}: {title} ({state}, {assignee})")
        lines.append("")

        lines.append("**This Week**")
        this_issues = p["this_week"]["issues"]
        if not this_issues:
            lines.append("- No updates")
        else:
            for i in this_issues:
                key = i.get("key") or "ISSUE"
                state = i.get("state") or "Unknown"
                assignee = i.get("assignee") or "Unassigned"
                title = i.get("title")
                lines.append(f"- {key}: {title} ({state}, {assignee})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
