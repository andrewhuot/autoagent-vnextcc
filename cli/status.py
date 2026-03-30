"""Status rendering helpers for the AutoAgent CLI home screen."""

from __future__ import annotations

from dataclasses import dataclass

import click


@dataclass
class StatusSnapshot:
    """Structured status data rendered by the CLI."""

    workspace_name: str
    workspace_path: str
    mode_label: str
    active_config_label: str
    active_config_summary: str
    eval_score_label: str
    eval_timestamp_label: str
    conversations_label: str
    safety_label: str
    cycles_run_label: str
    pending_review_cards: int
    pending_autofix_proposals: int
    deployment_label: str
    loop_label: str
    memory_label: str
    mcp_label: str
    model_label: str
    last_eval_tokens_label: str
    last_eval_cost_label: str
    last_optimize_cost_label: str
    next_action: str


def render_status(snapshot: StatusSnapshot, *, verbose: bool = False) -> None:
    """Render a colorful status home screen from a status snapshot."""
    click.echo(click.style("\nAutoAgent Status", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━")
    click.echo(click.style(f"  Workspace: {snapshot.workspace_name}", fg="cyan", bold=True))
    click.echo(f"  Path: {snapshot.workspace_path}")
    click.echo(f"  Mode: {snapshot.mode_label}")
    click.echo(f"  Active config: {snapshot.active_config_label}")
    click.echo(f"  Config: {snapshot.active_config_label}")
    click.echo(f"  Summary: {snapshot.active_config_summary}")
    click.echo(f"  Latest eval: {snapshot.eval_score_label} ({snapshot.eval_timestamp_label})")
    click.echo(f"  Eval score: {snapshot.eval_score_label}")
    click.echo(f"  Conversations: {snapshot.conversations_label}")
    click.echo(f"  Safety: {snapshot.safety_label}")
    click.echo(f"  Cycles run: {snapshot.cycles_run_label}")
    click.echo(f"  Pending review cards: {snapshot.pending_review_cards}")
    click.echo(f"  Pending AutoFix proposals: {snapshot.pending_autofix_proposals}")
    click.echo(f"  Deployment: {snapshot.deployment_label}")
    click.echo(f"  Loop: {snapshot.loop_label}")
    click.echo(f"  Memory: {snapshot.memory_label}")
    click.echo(f"  MCP: {snapshot.mcp_label}")
    click.echo(f"  Models: {snapshot.model_label}")
    click.echo(f"  Last eval tokens: {snapshot.last_eval_tokens_label}")
    click.echo(f"  Last eval cost: {snapshot.last_eval_cost_label}")
    click.echo(f"  Last optimize cost: {snapshot.last_optimize_cost_label}")

    if verbose:
        click.echo(click.style("\n  Home screen summary:", fg="cyan"))
        click.echo("  Use --json for machine-readable status output.")

    click.echo(f"\n  Next action: {snapshot.next_action}")
    click.echo(click.style(f"  Next step: {snapshot.next_action}", fg="green"))
