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


INTELLIGENCE_STORE_PATH = Path(".autoagent") / "intelligence_reports.json"


class TranscriptReportStore:
    """Persist imported transcript reports so CLI invocations can reuse them.

    The backend service is intentionally in-memory. The CLI needs a thin durable
    layer so `upload`, `report`, and `generate-agent` work across separate
    processes while still delegating analysis to the existing backend service.
    """

    def __init__(self, path: Path = INTELLIGENCE_STORE_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_reports(self) -> list[dict[str, Any]]:
        """Return stored report entries sorted newest first."""
        payload = self._load()
        reports = list(payload.get("reports", {}).values())
        reports.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=True)
        return reports

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Return a stored report entry by report ID."""
        payload = self._load()
        return payload.get("reports", {}).get(report_id)

    def save_report(
        self,
        *,
        report: dict[str, Any],
        archive_name: str,
        archive_base64: str,
    ) -> None:
        """Persist the report summary and original archive bytes."""
        payload = self._load()
        payload.setdefault("reports", {})
        report_id = str(report["report_id"])
        payload["reports"][report_id] = {
            "report_id": report_id,
            "archive_name": archive_name,
            "archive_base64": archive_base64,
            "created_at": float(report.get("created_at", 0.0)),
            "report": report,
        }
        self._save(payload)

    def _load(self) -> dict[str, Any]:
        """Load the report store, returning an empty payload when absent."""
        if not self.path.exists():
            return {"reports": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        """Write the report store atomically enough for CLI usage."""
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
        report = entry.get("report", {})
        archive_name = str(entry.get("archive_name", ""))[:24]
        conversation_count = int(report.get("conversation_count", 0))
        languages = ", ".join(report.get("languages", []))
        lines.append(
            f"{entry.get('report_id', ''):<12}  {archive_name:<24}  {conversation_count:>13}  {languages}"
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
    """Rebuild a backend report object from the stored archive payload."""
    archive_name = str(report_entry["archive_name"])
    archive_base64 = str(report_entry["archive_base64"])
    service = TranscriptIntelligenceService()
    report = service.import_archive(archive_name, archive_base64)
    return service, report.report_id, report.to_dict()


@click.group("intelligence")
def intelligence_group() -> None:
    """Run transcript intelligence workflows directly from the CLI."""


@intelligence_group.command("upload")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Output the full imported report as JSON.")
def upload_archive(archive: Path, json_output: bool) -> None:
    """Import a transcript archive without using the HTTP API."""
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


@intelligence_group.group("report")
def report_group() -> None:
    """Inspect stored transcript intelligence reports."""


@report_group.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output stored report summaries as JSON.")
def list_reports(json_output: bool) -> None:
    """List stored transcript intelligence reports."""
    entries = TranscriptReportStore().list_reports()
    if json_output:
        payload = [
            {
                "report_id": entry.get("report_id"),
                "archive_name": entry.get("archive_name"),
                "created_at": entry.get("created_at"),
                "report": entry.get("report"),
            }
            for entry in entries
        ]
        click.echo(json.dumps(payload, indent=2))
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

    report = dict(entry.get("report", {}))
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
    entry = TranscriptReportStore().get_report(report_id)
    if entry is None:
        raise click.ClickException(f"Unknown transcript intelligence report: {report_id}")

    service, replayed_report_id, replayed_report = _load_replayed_report(entry)
    prompt = _build_generation_prompt(replayed_report)
    generated = service.generate_agent_config(prompt, transcript_report_id=replayed_report_id)

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
