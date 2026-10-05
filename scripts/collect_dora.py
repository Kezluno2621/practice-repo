#!/usr/bin/env python3
"""Collect DORA metrics from the GitHub REST API and render assignment outputs."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

API_ROOT = "https://api.github.com"
DEFAULT_PERIOD_DAYS = 7
TERMINAL_STATES = {"success", "failure", "error"}
FAILED_STATES = {"failure", "error"}
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
TEMPLATE_PATH = ROOT / "dashboard" / "index.html"


def parse_timestamp(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp as an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return round(sum(items) / len(items), 2) if items else None


class GitHubAPI:
    def __init__(self, token: str) -> None:
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "practice-repo-dora-collector",
        }

    def get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API request failed ({exc.code}) at {url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API connection failed at {url}: {exc.reason}") from exc

    def paginated(self, path_or_url: str) -> list[dict[str, Any]]:
        """Read every page from a GitHub list endpoint."""
        separator = "&" if "?" in path_or_url else "?"
        base = path_or_url if path_or_url.startswith("http") else f"{API_ROOT}{path_or_url}"
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            url = f"{base}{separator}per_page=100&page={page}"
            payload = self.get_json(url)
            if not isinstance(payload, list):
                raise RuntimeError(f"Expected a JSON array from GitHub API at {url}")
            results.extend(payload)
            if len(payload) < 100:
                return results
            page += 1


@dataclass(frozen=True)
class DeploymentResult:
    deployment_id: int
    sha: str
    state: str
    completed_at: datetime


def collect_deployment_results(api: GitHubAPI, repository: str) -> list[DeploymentResult]:
    deployments = api.paginated(f"/repos/{repository}/deployments")
    results: list[DeploymentResult] = []
    for deployment in deployments:
        statuses = api.paginated(deployment["statuses_url"])
        terminal_statuses = [
            status
            for status in statuses
            if status.get("state") in TERMINAL_STATES and status.get("created_at")
        ]
        terminal = max(
            terminal_statuses,
            key=lambda status: parse_timestamp(status["created_at"]),
            default=None,
        )
        if terminal is None:
            continue
        completed_at = terminal.get("created_at") or terminal.get("updated_at")
        if not completed_at:
            continue
        results.append(
            DeploymentResult(
                deployment_id=int(deployment["id"]),
                sha=str(deployment["sha"]),
                state=str(terminal["state"]),
                completed_at=parse_timestamp(completed_at),
            )
        )
    return sorted(results, key=lambda item: item.completed_at)


def commit_time(api: GitHubAPI, repository: str, sha: str) -> datetime | None:
    encoded_sha = urllib.parse.quote(sha, safe="")
    commit = api.get_json(f"{API_ROOT}/repos/{repository}/commits/{encoded_sha}")
    details = commit.get("commit", {})
    timestamp = (details.get("committer") or {}).get("date")
    timestamp = timestamp or (details.get("author") or {}).get("date")
    return parse_timestamp(timestamp) if timestamp else None


def calculate_metrics(
    api: GitHubAPI,
    repository: str,
    results: list[DeploymentResult],
    period_start: datetime,
    period_days: int,
) -> dict[str, dict[str, float | int | str | None]]:
    in_period = [item for item in results if item.completed_at >= period_start]
    successes = [item for item in in_period if item.state == "success"]
    failures = [item for item in in_period if item.state in FAILED_STATES]

    lead_times: list[float] = []
    commit_cache: dict[str, datetime | None] = {}
    for deployment in successes:
        if deployment.sha not in commit_cache:
            commit_cache[deployment.sha] = commit_time(api, repository, deployment.sha)
        committed_at = commit_cache[deployment.sha]
        if committed_at and deployment.completed_at >= committed_at:
            lead_times.append((deployment.completed_at - committed_at).total_seconds() / 3600)

    restoration_times: list[float] = []
    for failure in failures:
        recovery = next(
            (
                item
                for item in results
                if item.state == "success" and item.completed_at > failure.completed_at
            ),
            None,
        )
        if recovery:
            restoration_times.append(
                (recovery.completed_at - failure.completed_at).total_seconds() / 3600
            )

    completed_count = len(successes) + len(failures)
    failure_rate = (
        round(len(failures) / completed_count * 100, 2) if completed_count else None
    )
    deployments_per_week = round(len(successes) * 7 / period_days, 2)

    return {
        "lead_time": {"value": mean(lead_times), "unit": "hours"},
        "deployment_frequency": {
            "value": deployments_per_week,
            "unit": "deployments/week",
            "deployment_count": len(successes),
        },
        "mttr": {"value": mean(restoration_times), "unit": "hours"},
        "change_failure_rate": {"value": failure_rate, "unit": "percent"},
    }


def display_metric(metric: dict[str, Any]) -> str:
    value = metric["value"]
    if value is None:
        return "N/A"
    units = {
        "hours": "hours",
        "deployments/week": "deployments/week",
        "percent": "%",
    }
    return f"{value:g} {units[metric['unit']]}"


def build_weekly_report(payload: dict[str, Any], start: datetime, end: datetime) -> str:
    metrics = payload["metrics"]
    available = sum(metric["value"] is not None for metric in metrics.values())
    summary = (
        f"{available} of 4 metrics were calculable from completed deployments in the "
        "selected period. N/A means GitHub did not contain enough applicable data; it is "
        "not treated as zero."
    )
    return f"""# Weekly DORA Report

## Period
{start.date().isoformat()} ~ {end.date().isoformat()} (UTC)

## DORA Metrics

| Metric | Result |
|---|---:|
| Lead Time | {display_metric(metrics['lead_time'])} |
| Deployment Frequency | {display_metric(metrics['deployment_frequency'])} |
| MTTR | {display_metric(metrics['mttr'])} |
| Change Failure Rate | {display_metric(metrics['change_failure_rate'])} |

## Summary

{summary}
"""


def write_outputs(payload: dict[str, Any], start: datetime, end: datetime) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (OUTPUT_DIR / "dora-metrics.json").write_text(json_text + "\n", encoding="utf-8")
    report = build_weekly_report(payload, start, end)
    (OUTPUT_DIR / "weekly-report.md").write_text(report, encoding="utf-8")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    safe_json = json_text.replace("<", "\\u003c").replace(">", "\\u003e")
    if "__DORA_METRICS_JSON__" not in template:
        raise RuntimeError(f"Dashboard placeholder is missing from {TEMPLATE_PATH}")
    dashboard = template.replace("__DORA_METRICS_JSON__", safe_json)
    (OUTPUT_DIR / "dashboard.html").write_text(dashboard, encoding="utf-8")


def positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def main() -> int:
    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required (use the Actions github.token value)")
    if not repository or "/" not in repository:
        raise RuntimeError("GITHUB_REPOSITORY must use the owner/repository format")

    period_days = positive_int("PERIOD_DAYS", DEFAULT_PERIOD_DAYS)
    generated_at = datetime.now(timezone.utc)
    period_start = generated_at - timedelta(days=period_days)
    api = GitHubAPI(token)

    print(f"Collecting deployment data for {repository} (last {period_days} days)...")
    results = collect_deployment_results(api, repository)
    print(f"Found {len(results)} deployments with a terminal status.")
    metrics = calculate_metrics(api, repository, results, period_start, period_days)
    payload = {
        "repository": repository,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "period_days": period_days,
        "metrics": metrics,
    }
    write_outputs(payload, period_start, generated_at)
    print(f"Generated DORA outputs in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
