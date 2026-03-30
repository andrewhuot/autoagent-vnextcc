"""Usage and budget surfaces for the AutoAgent CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from agent.config.runtime import load_runtime_config
from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from optimizer.cost_tracker import CostTracker


def _unwrap_eval_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data")
    if isinstance(payload, dict) and isinstance(data.get("status"), str):
        return payload
    return data


def _candidate_eval_result_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for base in (root, root / ".autoagent"):
        if not base.exists():
            continue
        candidates.extend(path for path in base.glob("*eval*result*.json") if path.is_file())
        candidates.extend(path for path in base.glob("*results*.json") if path.is_file())
    return candidates


def load_latest_eval_usage(root: str | Path = ".") -> dict[str, Any] | None:
    """Load the latest eval token/cost snapshot from disk."""
    workspace_root = Path(root)
    candidates = _candidate_eval_result_paths(workspace_root)
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    data = _unwrap_eval_payload(payload)
    return {
        "path": str(latest),
        "run_id": data.get("run_id"),
        "total_tokens": int(data.get("total_tokens", 0) or 0),
        "estimated_cost_usd": float(data.get("estimated_cost_usd", 0.0) or 0.0),
        "composite": float(data.get("composite", 0.0) or 0.0),
    }


def build_usage_snapshot(root: str | Path = ".") -> dict[str, Any]:
    """Build the workspace usage and budget summary."""
    workspace_root = Path(root)
    runtime = load_runtime_config(str(workspace_root / "autoagent.yaml"))
    tracker_path = workspace_root / runtime.budget.tracker_db_path
    tracker = CostTracker(
        db_path=str(tracker_path),
        per_cycle_budget_dollars=runtime.budget.per_cycle_dollars,
        daily_budget_dollars=runtime.budget.daily_dollars,
        stall_threshold_cycles=runtime.budget.stall_threshold_cycles,
    )
    tracker_summary = tracker.summary()
    recent_cycles = tracker.recent_cycles(limit=1)
    last_optimize = recent_cycles[-1] if recent_cycles else None
    last_eval = load_latest_eval_usage(workspace_root)

    return {
        "workspace_root": str(workspace_root.resolve()),
        "last_eval": last_eval,
        "last_optimize": last_optimize,
        "workspace_spend_usd": tracker_summary["total_spend"],
        "today_spend_usd": tracker_summary["today_spend"],
        "configured_budget_usd": runtime.budget.daily_dollars,
        "budget_remaining_usd": round(
            max(0.0, runtime.budget.daily_dollars - tracker_summary["today_spend"]),
            6,
        ),
        "cost_per_improvement": tracker_summary["cost_per_improvement"],
    }


def enforce_workspace_budget(
    max_budget_usd: float | None,
    *,
    root: str | Path = ".",
) -> tuple[bool, str | None, dict[str, Any]]:
    """Return whether the workspace can continue within the requested max budget."""
    snapshot = build_usage_snapshot(root)
    if max_budget_usd is None:
        return True, None, snapshot
    spent = float(snapshot["workspace_spend_usd"])
    if spent >= max_budget_usd:
        message = (
            f"Budget guard reached: workspace spend ${spent:.2f} "
            f">= max budget ${max_budget_usd:.2f}."
        )
        return False, message, snapshot
    return True, None, snapshot


@click.command("usage")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def usage_command(json_output: bool = False) -> None:
    """Show recent eval/optimize cost and budget state."""
    workspace_root = Path(".")
    if not (workspace_root / ".autoagent").exists():
        raise click_error("No AutoAgent workspace found.")

    snapshot = build_usage_snapshot(workspace_root)
    if json_output:
        click.echo(render_json_envelope("ok", snapshot, next_command="autoagent status"))
        return

    click.echo("AutoAgent Usage")
    click.echo("━━━━━━━━━━━━━━━")
    last_eval = snapshot.get("last_eval") or {}
    last_optimize = snapshot.get("last_optimize") or {}
    click.echo(
        f"Last eval: tokens={last_eval.get('total_tokens', 0)} "
        f"cost=${float(last_eval.get('estimated_cost_usd', 0.0)):.2f}"
    )
    if last_optimize:
        click.echo(
            f"Last optimize: ${float(last_optimize.get('spent_dollars', 0.0)):.2f} "
            f"({last_optimize.get('cycle_id', 'unknown cycle')})"
        )
    else:
        click.echo("Last optimize: n/a")
    click.echo(f"Workspace spend: ${float(snapshot['workspace_spend_usd']):.2f}")
    click.echo(f"Configured budget: ${float(snapshot['configured_budget_usd']):.2f}")
    click.echo(f"Budget remaining: ${float(snapshot['budget_remaining_usd']):.2f}")
