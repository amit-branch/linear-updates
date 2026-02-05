from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import typer
from rich.console import Console

from .config import AppConfig, load_config
from .draft import draft_weekly_update, validate_access
from .linear_client import LinearAPIError, LinearClient
from .markdown import write_text_atomic
from .openrouter_client import OpenRouterError

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _handle_error(error: Exception, *, debug: bool) -> None:
    if debug:
        raise
    if isinstance(error, (LinearAPIError, OpenRouterError)):
        console.print(f"[red]{error}[/red]")
    elif isinstance(error, httpx.HTTPError):
        console.print(f"[red]Network error: {error}[/red]")
    else:
        console.print(f"[red]{type(error).__name__}: {error}[/red]")
    raise typer.Exit(1)


@app.command()
def validate(
    env_file: Path | None = typer.Option(
        None, "--env-file", exists=True, dir_okay=False, readable=True
    ),
    team_id: str | None = typer.Option(None, "--team-id"),
    team_key: str | None = typer.Option(None, "--team-key"),
    debug: bool = typer.Option(False, "--debug", help="Show full traceback on error."),
):
    """Validate Linear access and team/cycle visibility."""
    try:
        config = load_config(env_file=env_file, team_id=team_id, team_key=team_key)
        result = validate_access(config)
        console.print("[green]OK[/green]")
        console.print_json(json.dumps(result, indent=2))
    except Exception as e:  # noqa: BLE001
        _handle_error(e, debug=debug)


@app.command()
def draft(
    env_file: Path | None = typer.Option(
        None, "--env-file", exists=True, dir_okay=False, readable=True
    ),
    team_id: str | None = typer.Option(None, "--team-id"),
    team_key: str | None = typer.Option(None, "--team-key"),
    output: Path | None = typer.Option(None, "--output", dir_okay=False),
    save_raw: Path | None = typer.Option(
        None, "--save-raw", dir_okay=False, help="Write raw facts JSON to this path."
    ),
    no_llm: bool = typer.Option(
        False, "--no-llm", help="Skip OpenRouter; write fact-based markdown instead."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print markdown to stdout; do not write the file."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
    debug: bool = typer.Option(False, "--debug", help="Show full traceback on error."),
):
    """Draft the weekly update and overwrite the output markdown."""
    try:
        config: AppConfig = load_config(
            env_file=env_file, team_id=team_id, team_key=team_key, output_path=output
        )

        status_ctx = console.status("[bold blue]Starting...", spinner="dots")
        if not quiet and not dry_run:
            status_ctx.start()

        def on_progress(msg: str) -> None:
            if not quiet and not dry_run:
                status_ctx.update(f"[bold blue]{msg}")

        markdown, facts = draft_weekly_update(
            config=config, use_llm=not no_llm, on_progress=on_progress
        )

        if not quiet and not dry_run:
            status_ctx.stop()

        if save_raw is not None:
            save_raw.parent.mkdir(parents=True, exist_ok=True)
            save_raw.write_text(
                json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

        if dry_run:
            console.print(markdown)
            raise typer.Exit(0)

        write_text_atomic(config.output_path, markdown, encoding="utf-8")
        console.print(f"[green]✓[/green] Wrote: {config.output_path}")
    except Exception as e:  # noqa: BLE001
        if not quiet:
            status_ctx.stop()
        _handle_error(e, debug=debug)


def _normalize_name(name: str) -> str:
    """Normalize project name for matching (handle unicode dashes, etc)."""
    # Replace various unicode dashes with regular hyphen
    return name.replace("‑", "-").replace("–", "-").replace("—", "-").strip()


def _parse_project_updates(markdown: str, facts: dict) -> list[dict]:
    """Parse the generated markdown to extract per-project updates.

    Returns a list of dicts with 'project_id', 'project_name', and 'body'.
    """
    # Build a normalized name -> (id, original_name) lookup from facts
    name_to_info: dict[str, tuple[str, str]] = {}
    for p in facts.get("projects", []):
        normalized = _normalize_name(p["name"])
        name_to_info[normalized] = (p["id"], p["name"])

    # Split markdown by ## Project Name headers
    # Pattern: ## followed by project name (until next ## or end)
    pattern = r"^## (.+?)$"
    sections = re.split(pattern, markdown, flags=re.MULTILINE)

    # sections = ['preamble', 'Project1', 'content1', 'Project2', 'content2', ...]
    results: list[dict] = []
    i = 1  # Skip preamble
    while i < len(sections) - 1:
        project_name_raw = sections[i].strip()
        project_name_normalized = _normalize_name(project_name_raw)
        content = sections[i + 1].strip()
        info = name_to_info.get(project_name_normalized)
        if info and content:
            project_id, original_name = info
            results.append({
                "project_id": project_id,
                "project_name": original_name,
                "body": content,
            })
        i += 2

    return results


@app.command("post-to-linear")
def post_to_linear(
    env_file: Path | None = typer.Option(
        None, "--env-file", exists=True, dir_okay=False, readable=True
    ),
    team_id: str | None = typer.Option(None, "--team-id"),
    team_key: str | None = typer.Option(None, "--team-key"),
    output: Path | None = typer.Option(None, "--output", dir_okay=False),
    save_raw: Path | None = typer.Option(
        None, "--save-raw", dir_okay=False, help="Write raw facts JSON to this path."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be posted without actually posting."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
    debug: bool = typer.Option(False, "--debug", help="Show full traceback on error."),
):
    """Generate weekly update and post it to Linear as project updates."""
    status_ctx = console.status("[bold blue]Starting...", spinner="dots")
    try:
        config: AppConfig = load_config(
            env_file=env_file, team_id=team_id, team_key=team_key, output_path=output
        )

        if not quiet:
            status_ctx.start()

        def on_progress(msg: str) -> None:
            if not quiet:
                status_ctx.update(f"[bold blue]{msg}")

        # Generate the update
        markdown, facts = draft_weekly_update(
            config=config, use_llm=True, on_progress=on_progress
        )

        # Parse into per-project updates
        project_updates = _parse_project_updates(markdown, facts)

        if not project_updates:
            if not quiet:
                status_ctx.stop()
            console.print("[yellow]No project updates found to post.[/yellow]")
            raise typer.Exit(0)

        if dry_run:
            if not quiet:
                status_ctx.stop()
            console.print(f"\n[bold]Would post {len(project_updates)} project updates:[/bold]\n")
            for pu in project_updates:
                console.print(f"[cyan]## {pu['project_name']}[/cyan]")
                console.print(pu["body"])
                console.print()
            raise typer.Exit(0)

        # Post each project update to Linear
        client = LinearClient(api_key=config.linear_api_key)
        posted_count = 0
        for pu in project_updates:
            on_progress(f"Posting update for {pu['project_name']}...")
            try:
                # Fetch current health to preserve it
                current_health = client.get_project_health(pu["project_id"])
                result = client.create_project_update(
                    project_id=pu["project_id"],
                    body=pu["body"],
                    health=current_health,
                )
                if result.get("success"):
                    posted_count += 1
                    url = result.get("projectUpdate", {}).get("url", "")
                    if not quiet:
                        status_ctx.stop()
                        console.print(
                            f"[green]✓[/green] Posted: {pu['project_name']}"
                            + (f" ({url})" if url else "")
                        )
                        status_ctx.start()
            except LinearAPIError as e:
                if not quiet:
                    status_ctx.stop()
                console.print(f"[red]✗[/red] Failed to post {pu['project_name']}: {e}")
                if not quiet:
                    status_ctx.start()

        if not quiet:
            status_ctx.stop()

        # Save raw facts if requested
        if save_raw is not None:
            save_raw.parent.mkdir(parents=True, exist_ok=True)
            save_raw.write_text(
                json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

        # Also write the combined markdown file
        write_text_atomic(config.output_path, markdown, encoding="utf-8")
        console.print(f"[green]✓[/green] Wrote: {config.output_path}")
        console.print(
            f"\n[bold green]Done![/bold green] Posted {posted_count}/{len(project_updates)} "
            "project updates to Linear."
        )

    except Exception as e:  # noqa: BLE001
        if not quiet:
            status_ctx.stop()
        _handle_error(e, debug=debug)
