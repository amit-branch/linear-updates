from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    linear_api_key: str
    team_id: str | None
    team_key: str | None
    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_provider: str | None  # e.g., "Cerebras" to prefer a specific provider
    output_path: Path


def load_config(
    *,
    env_file: Path | None = None,
    team_id: str | None = None,
    team_key: str | None = None,
    output_path: Path | None = None,
) -> AppConfig:
    if env_file is not None:
        load_dotenv(env_file)
    else:
        load_dotenv()

    import os

    linear_api_key = os.getenv("LINEAR_API_KEY", "").strip()
    if not linear_api_key:
        raise ValueError("Missing LINEAR_API_KEY")

    resolved_team_id = (team_id or os.getenv("LINEAR_TEAM_ID") or "").strip() or None
    resolved_team_key = (team_key or os.getenv("LINEAR_TEAM_KEY") or "").strip() or None

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or None
    openrouter_model = os.getenv("OPENROUTER_MODEL", "").strip() or "moonshotai/kimi-k2.5"
    openrouter_provider = os.getenv("OPENROUTER_PROVIDER", "").strip() or None

    resolved_output = output_path or Path(
        os.getenv("OUTPUT_PATH", "").strip() or "updates/weekly_update.md"
    )

    return AppConfig(
        linear_api_key=linear_api_key,
        team_id=resolved_team_id,
        team_key=resolved_team_key,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        openrouter_provider=openrouter_provider,
        output_path=resolved_output,
    )
