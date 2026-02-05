from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .models import Comment, Cycle, Issue, IssueHistory, Project, Team
from .time_utils import parse_linear_datetime


class LinearAPIError(RuntimeError):
    def __init__(self, message: str, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass
class LinearClient:
    api_key: str
    base_url: str = "https://api.linear.app/graphql"
    timeout_s: float = 30.0

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_s,
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
        )

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._client() as client:
            resp = client.post(self.base_url, json={"query": query, "variables": variables or {}})
            payload: dict[str, Any] | None = None
            try:
                payload = resp.json()
            except Exception:
                payload = None

        if resp.status_code >= 400:
            if payload and payload.get("errors"):
                msg = payload["errors"][0].get("message") or "Linear GraphQL error"
                raise LinearAPIError(
                    f"Linear GraphQL error (HTTP {resp.status_code}): {msg}",
                    errors=payload["errors"],
                )
            raise LinearAPIError(
                f"Linear HTTP {resp.status_code}: {resp.text[:500].strip() or 'No response body'}"
            )

        if payload is None:
            raise LinearAPIError("Linear response was not valid JSON.")

        if "errors" in payload and payload["errors"]:
            msg = payload["errors"][0].get("message") or "Linear GraphQL error"
            raise LinearAPIError(msg, errors=payload["errors"])

        data = payload.get("data")
        if data is None:
            raise LinearAPIError("Missing 'data' in Linear response", errors=payload.get("errors"))
        return data

    def list_teams(self) -> list[Team]:
        data = self.graphql(
            """
            query Teams {
              teams {
                nodes { id name key }
              }
            }
            """
        )
        nodes = data["teams"]["nodes"]
        return [Team(id=n["id"], name=n["name"], key=n.get("key")) for n in nodes]

    def list_team_cycles(
        self, team_id: str, *, first: int = 50, max_pages: int = 20
    ) -> list[Cycle]:
        query = """
        query TeamCycles($teamId: String!, $first: Int!, $after: String) {
          team(id: $teamId) {
            id
            name
            cycles(first: $first, after: $after) {
              nodes { id name number startsAt endsAt }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        cycles: list[Cycle] = []
        after: str | None = None
        for _ in range(max_pages):
            data = self.graphql(query, {"teamId": team_id, "first": first, "after": after})
            conn = data["team"]["cycles"]
            for n in conn["nodes"]:
                cycles.append(
                    Cycle(
                        id=n["id"],
                        name=n.get("name"),
                        number=n.get("number"),
                        starts_at=parse_linear_datetime(n["startsAt"]),
                        ends_at=parse_linear_datetime(n["endsAt"]),
                    )
                )
            page = conn["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        return cycles

    def list_team_projects(
        self, team_id: str, *, first: int = 50, max_pages: int = 20
    ) -> list[Project]:
        # Linear's project status field naming can vary (e.g., `status` vs `projectStatus`).
        queries: list[tuple[str, str]] = [
            (
                "status",
                """
                query TeamProjects($teamId: String!, $first: Int!, $after: String) {
                  team(id: $teamId) {
                    projects(first: $first, after: $after) {
                      nodes { id name url status { name } }
                      pageInfo { hasNextPage endCursor }
                    }
                  }
                }
                """,
            ),
            (
                "projectStatus",
                """
                query TeamProjects($teamId: String!, $first: Int!, $after: String) {
                  team(id: $teamId) {
                    projects(first: $first, after: $after) {
                      nodes { id name url projectStatus { name } }
                      pageInfo { hasNextPage endCursor }
                    }
                  }
                }
                """,
            ),
        ]

        last_err: Exception | None = None
        for field_name, query in queries:
            try:
                projects: list[Project] = []
                after: str | None = None
                for _ in range(max_pages):
                    data = self.graphql(query, {"teamId": team_id, "first": first, "after": after})
                    conn = data["team"]["projects"]
                    for n in conn["nodes"]:
                        status_obj = n.get(field_name) or {}
                        projects.append(
                            Project(
                                id=n["id"],
                                name=n["name"],
                                url=n.get("url"),
                                status_name=(
                                    status_obj.get("name") if isinstance(status_obj, dict) else None
                                ),
                            )
                        )
                    page = conn["pageInfo"]
                    if not page["hasNextPage"]:
                        break
                    after = page["endCursor"]
                return projects
            except Exception as e:  # noqa: BLE001 - used for fallback across schema variants
                last_err = e
                continue

        raise LinearAPIError(f"Failed to query team projects (status field mismatch?): {last_err}")

    def list_issues_for_project_cycle(
        self, *, project_id: str, cycle_id: str, first: int = 50, max_pages: int = 50
    ) -> list[Issue]:
        query = """
        query Issues($projectId: ID, $cycleId: ID, $first: Int!, $after: String) {
          issues(
            first: $first,
            after: $after,
            filter: {
              project: { id: { eq: $projectId } }
              cycle: { id: { eq: $cycleId } }
            }
          ) {
            nodes {
              id
              identifier
              title
              url
              state { name }
              assignee { name }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        issues: list[Issue] = []
        after: str | None = None
        for _ in range(max_pages):
            data = self.graphql(
                query,
                {"projectId": project_id, "cycleId": cycle_id, "first": first, "after": after},
            )
            conn = data["issues"]
            for n in conn["nodes"]:
                issues.append(
                    Issue(
                        id=n["id"],
                        identifier=n.get("identifier"),
                        title=n["title"],
                        url=n.get("url"),
                        state_name=(n.get("state") or {}).get("name"),
                        assignee_name=(n.get("assignee") or {}).get("name"),
                    )
                )
            page = conn["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        return issues

    def list_issue_comments(
        self, issue_id: str, *, first: int = 50, max_pages: int = 50
    ) -> list[Comment]:
        query = """
        query IssueComments($issueId: String!, $first: Int!, $after: String) {
          issue(id: $issueId) {
            id
            comments(first: $first, after: $after) {
              nodes { id createdAt body user { name } }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        comments: list[Comment] = []
        after: str | None = None
        for _ in range(max_pages):
            data = self.graphql(query, {"issueId": issue_id, "first": first, "after": after})
            conn = data["issue"]["comments"]
            for n in conn["nodes"]:
                comments.append(
                    Comment(
                        id=n["id"],
                        created_at=parse_linear_datetime(n["createdAt"]),
                        body=n.get("body") or "",
                        author_name=(n.get("user") or {}).get("name"),
                    )
                )
            page = conn["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        return comments

    def list_issue_history(
        self, issue_id: str, *, first: int = 50, max_pages: int = 50
    ) -> list[IssueHistory]:
        query = """
        query IssueHistory($issueId: String!, $first: Int!, $after: String) {
          issue(id: $issueId) {
            id
            history(first: $first, after: $after) {
              nodes {
                id
                createdAt
                fromState { name }
                toState { name }
              }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        history: list[IssueHistory] = []
        after: str | None = None
        for _ in range(max_pages):
            data = self.graphql(query, {"issueId": issue_id, "first": first, "after": after})
            conn = data["issue"]["history"]
            for n in conn["nodes"]:
                history.append(
                    IssueHistory(
                        id=n["id"],
                        created_at=parse_linear_datetime(n["createdAt"]),
                        type=None,  # Not available in Linear API
                        from_state=(n.get("fromState") or {}).get("name"),
                        to_state=(n.get("toState") or {}).get("name"),
                    )
                )
            page = conn["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        return history

    def get_project_health(self, project_id: str) -> str | None:
        """Get the current health status of a project.

        Returns one of: 'onTrack', 'atRisk', 'offTrack', or None if not set.
        """
        query = """
        query ProjectHealth($projectId: String!) {
          project(id: $projectId) {
            id
            health
          }
        }
        """
        try:
            data = self.graphql(query, {"projectId": project_id})
            return data.get("project", {}).get("health")
        except LinearAPIError:
            return None

    def create_project_update(
        self, *, project_id: str, body: str, health: str | None = None
    ) -> dict[str, Any]:
        """Create a project update in Linear.

        Args:
            project_id: The Linear project ID
            body: The update content in markdown format
            health: Optional health status ('onTrack', 'atRisk', 'offTrack').
                    If provided, preserves this health status.

        Returns:
            Dict with 'success' and 'projectUpdate' containing 'id' and 'url'
        """
        mutation = """
        mutation CreateProjectUpdate($input: ProjectUpdateCreateInput!) {
          projectUpdateCreate(input: $input) {
            success
            projectUpdate {
              id
              url
            }
          }
        }
        """
        input_data: dict[str, Any] = {"projectId": project_id, "body": body}
        if health:
            input_data["health"] = health
        data = self.graphql(mutation, {"input": input_data})
        return data["projectUpdateCreate"]
