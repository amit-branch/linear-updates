from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Team:
    id: str
    key: str | None
    name: str


@dataclass(frozen=True)
class Cycle:
    id: str
    name: str | None
    number: int | None
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    url: str | None
    status_name: str | None


@dataclass(frozen=True)
class Issue:
    id: str
    identifier: str | None
    title: str
    url: str | None
    state_name: str | None
    assignee_name: str | None


@dataclass(frozen=True)
class Comment:
    id: str
    created_at: datetime
    body: str
    author_name: str | None


@dataclass(frozen=True)
class IssueHistory:
    id: str
    created_at: datetime
    type: str | None
    from_state: str | None
    to_state: str | None
