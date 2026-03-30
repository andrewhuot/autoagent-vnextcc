"""CLI commands for transcript intelligence workflows.

These commands keep transcript analysis in-process so operators can upload and
reuse archives without starting the API server or shelling out to curl.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import click
import yaml

from optimizer.transcript_intelligence import TranscriptIntelligenceService
from shared.transcript_report_store import TranscriptReportStore


def _echo_deprecation(old: str, new: str) -> None:
    """Print a consistent deprecation warning for hidden compatibility aliases."""
    click.echo(
        click.style(
            f"Deprecated: `{old}` is kept for backward compatibility. Use `{new}` instead.",
            fg="yellow",
        )
    )


def _invocation_cwd() -> Path:
    """Return the cwd from when the CLI invocation started."""
    ctx = click.get_current_context(silent=True)
    root = ctx.find_root() if ctx is not None else None
    meta = getattr(root, "meta", {}) if root is not None else {}
    raw_cwd = meta.get("invocation_cwd")
    return Path(raw_cwd).resolve() if raw_cwd else Path.cwd().resolve()


def _resolve_input_path(path: Path) -> Path:
    """Resolve user-supplied input paths against the original invocation cwd."""
    return path if path.is_absolute() else (_invocation_cwd() / path).resolve()


def _report_payload(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the direct report payload from either supported store shape."""

    report = entry.get("report")
    if isinstance(report, dict):
        return dict(report)
    return dict(entry)


def _format_report_table(entries: list[dict[str, Any]]) -> str:
    """Render a compact human-readable report listing."""
    if not entries:
        return "No transcript intelligence reports found."

    lines = [
        "Transcript intelligence reports:",
        f"{'Report ID':<12}  {'Archive':<24}  {'Conversations':>13}  {'Languages'}",
        f"{'─' * 12}  {'─' * 24}  {'─' * 13}  {'─' * 18}",
    ]
    for entry in entries:
        report = _report_payload(entry)
        archive_name = str(entry.get("archive_name", ""))[:24]
        conversation_count = int(report.get("conversation_count", 0))
        languages = ", ".join(report.get("languages", []))
        lines.append(
            f"{report.get('report_id', ''):<12}  {archive_name:<24}  {conversation_count:>13}  {languages}"
        )
    return "\n".join(lines)


def _render_report(report: dict[str, Any]) -> str:
    """Render a single transcript report for terminal output."""
    missing_intents = report.get("missing_intents", [])
    top_gaps = ", ".join(item.get("intent", "") for item in missing_intents[:5]) or "none"
    languages = ", ".join(report.get("languages", [])) or "unknown"
    asset = report.get("knowledge_asset", {}) or {}
    lines = [
        "Transcript intelligence report",
        f"Report ID: {report.get('report_id', '')}",
        f"Archive: {report.get('archive_name', '')}",
        f"Conversation count: {report.get('conversation_count', 0)}",
        f"Languages: {languages}",
        f"Top gaps: {top_gaps}",
    ]
    asset_id = asset.get("asset_id")
    if asset_id:
        lines.append(f"Knowledge asset: {asset_id} ({asset.get('entry_count', 0)} entries)")
    if report.get("intent_accuracy") is not None:
        accuracy = float(report["intent_accuracy"])
        lines.append(
            "Intent accuracy: "
            f"{accuracy:.1%} across {int(report.get('intent_accuracy_samples', 0))} labeled samples"
        )
    return "\n".join(lines)


def _build_generation_prompt(report: dict[str, Any]) -> str:
    """Synthesize a report-driven prompt for agent generation.

    The backend generator expects a natural-language brief plus an optional
    transcript report ID. This helper turns stored report findings into that
    brief so the CLI can generate from a report ID alone.
    """

    languages = ", ".join(report.get("languages", [])) or "English"
    missing_intents = report.get("missing_intents", []) or []
    workflow_suggestions = report.get("workflow_suggestions", []) or []
    gap_text = ", ".join(item.get("intent", "") for item in missing_intents[:4]) or "general support"
    workflow_text = "; ".join(
        str(item.get("recommendation") or item.get("title") or item.get("summary") or "").strip()
        for item in workflow_suggestions[:3]
        if str(item.get("recommendation") or item.get("title") or item.get("summary") or "").strip()
    )

    prompt = (
        f"Build a transcript-informed customer support agent from archive {report.get('archive_name', 'transcripts')}. "
        f"Support these languages: {languages}. "
        f"Address these coverage gaps: {gap_text}. "
        "Prefer self-service resolution, require identity verification before account-changing actions, "
        "and preserve high-quality human escalation handoff."
    )
    if workflow_text:
        prompt += f" Incorporate these workflow improvements: {workflow_text}."
    return prompt


def _load_replayed_report(
    report_entry: dict[str, Any],
) -> tuple[TranscriptIntelligenceService, str, dict[str, Any]]:
    """Compatibility helper for existing runner imports.

    The new shared store keeps the report payload itself durable, so this helper
    simply reloads the stored report when possible and falls back to the passed
    payload if the report cannot be refreshed.
    """

    service = TranscriptIntelligenceService()
    report_id = str(report_entry["report_id"])
    report = service.get_report(report_id)
    if report is not None:
        return service, report.report_id, report.to_dict()
    return service, report_id, _report_payload(report_entry)


@click.group("intelligence")
def intelligence_group() -> None:
    """Run transcript intelligence workflows directly from the CLI.

    Examples:
      autoagent intelligence upload support-archive.zip
      autoagent intelligence report list
      autoagent intelligence generate-agent <report-id> --output configs/v003_transcript.yaml
    """


def _import_archive_impl(archive: Path, json_output: bool) -> None:
    """Import a transcript archive and optionally emit JSON."""
    archive = _resolve_input_path(archive)
    if not archive.exists():
        raise click.ClickException(f"File does not exist: {archive}")
    if archive.is_dir():
        raise click.ClickException(f"Expected a file, got directory: {archive}")

    service = TranscriptIntelligenceService()
    archive_base64 = base64.b64encode(archive.read_bytes()).decode("ascii")

    try:
        report = service.import_archive(archive.name, archive_base64)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    report_dict = report.to_dict()
    TranscriptReportStore().save_report(
        report=report_dict,
        archive_name=archive.name,
        archive_base64=archive_base64,
    )

    if json_output:
        click.echo(json.dumps(report_dict, indent=2))
        return

    click.echo("Transcript archive imported.")
    click.echo(f"Report ID: {report.report_id}")
    click.echo(f"Archive: {report.archive_name}")
    click.echo(f"Conversation count: {len(report.conversations)}")
    click.echo(f"Languages: {', '.join(report.languages) or 'unknown'}")


@intelligence_group.command("import")
@click.argument("archive", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Output the full imported report as JSON.")
def import_archive(archive: Path, json_output: bool) -> None:
    """Import a transcript archive without using the HTTP API."""
    _import_archive_impl(archive, json_output=json_output)


@intelligence_group.command("upload", hidden=True)
@click.argument("archive", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Output the full imported report as JSON.")
def upload_archive_alias(archive: Path, json_output: bool) -> None:
    """Deprecated alias for `autoagent intelligence import`."""
    _echo_deprecation("autoagent intelligence upload", "autoagent intelligence import")
    _import_archive_impl(archive, json_output=json_output)


@intelligence_group.group("report")
def report_group() -> None:
    """Inspect stored transcript intelligence reports."""


@report_group.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output stored report summaries as JSON.")
def list_reports(json_output: bool) -> None:
    """List stored transcript intelligence reports."""
    entries = TranscriptReportStore().list_reports()
    if json_output:
        click.echo(json.dumps([_report_payload(entry) for entry in entries], indent=2))
        return
    click.echo(_format_report_table(entries))


@report_group.command("show")
@click.argument("report_id")
@click.option("--json", "json_output", is_flag=True, help="Output the stored report as JSON.")
def show_report(report_id: str, json_output: bool) -> None:
    """Show a stored transcript intelligence report."""
    entry = TranscriptReportStore().get_report(report_id)
    if entry is None:
        raise click.ClickException(f"Unknown transcript intelligence report: {report_id}")

    report = _report_payload(entry)
    if json_output:
        click.echo(json.dumps(report, indent=2))
        return
    click.echo(_render_report(report))


@intelligence_group.command("generate-agent")
@click.argument("report_id")
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the generated agent config to this file.")
@click.option("--json", "json_output", is_flag=True, help="Output the generated config as JSON.")
def generate_agent(report_id: str, output_path: Path | None, json_output: bool) -> None:
    """Generate an agent config from a stored transcript intelligence report."""
    service = TranscriptIntelligenceService()
    report = service.get_report(report_id)
    if report is None:
        raise click.ClickException(f"Unknown transcript intelligence report: {report_id}")

    report_dict = report.to_dict()
    prompt = _build_generation_prompt(report_dict)
    generated = service.generate_agent_config(prompt, transcript_report_id=report.report_id)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml.safe_dump(generated, sort_keys=False), encoding="utf-8")

    if json_output:
        click.echo(json.dumps(generated, indent=2))
        return

    click.echo("Generated agent config from transcript intelligence.")
    click.echo(f"Report ID: {report_id}")
    click.echo(f"Agent name: {generated.get('metadata', {}).get('agent_name', 'unknown')}")
    click.echo(f"Created from: {generated.get('metadata', {}).get('created_from', 'unknown')}")
    if output_path is not None:
        click.echo(f"Wrote config: {output_path}")
    else:
        click.echo(yaml.safe_dump(generated, sort_keys=False).rstrip())
