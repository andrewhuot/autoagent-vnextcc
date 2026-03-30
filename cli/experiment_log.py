"""Helpers for append-only optimization experiment logging."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

EXPERIMENT_LOG_HEADER = [
    "cycle",
    "timestamp",
    "score_before",
    "score_after",
    "delta",
    "status",
    "description",
]
DEFAULT_EXPERIMENT_LOG_PATH = Path(".autoagent/experiment_log.tsv")
STATUS_COLORS = {
    "keep": "green",
    "discard": "red",
    "skip": "yellow",
    "crash": "magenta",
}


@dataclass(frozen=True)
class ExperimentLogEntry:
    """Represent one completed optimization cycle so CLI views stay consistent."""

    cycle: int
    timestamp: str
    score_before: float | None
    score_after: float | None
    delta: float | None
    status: str
    description: str

    def to_row(self) -> dict[str, str]:
        """Serialize the entry into TSV-safe string values."""
        return {
            "cycle": str(self.cycle),
            "timestamp": self.timestamp,
            "score_before": _format_tsv_number(self.score_before),
            "score_after": _format_tsv_number(self.score_after),
            "delta": _format_tsv_number(self.delta),
            "status": self.status,
            "description": _sanitize_text(self.description),
        }

    def to_dict(self) -> dict[str, int | float | str | None]:
        """Expose JSON-friendly values without lossy string formatting."""
        return {
            "cycle": self.cycle,
            "timestamp": self.timestamp,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "delta": self.delta,
            "status": self.status,
            "description": self.description,
        }


def default_log_path() -> Path:
    """Centralize the log path so optimize and reporting commands cannot drift."""
    return DEFAULT_EXPERIMENT_LOG_PATH


def utc_timestamp() -> str:
    """Use a stable UTC timestamp format for log rows and machine parsing."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_delta(score_before: float | None, score_after: float | None) -> float | None:
    """Compute the score delta when both endpoints are present."""
    if score_before is None or score_after is None:
        return None
    return score_after - score_before


def make_entry(
    *,
    cycle: int,
    status: str,
    description: str,
    score_before: float | None,
    score_after: float | None,
    timestamp: str | None = None,
) -> ExperimentLogEntry:
    """Build a validated log entry with an auto-computed delta."""
    return ExperimentLogEntry(
        cycle=cycle,
        timestamp=timestamp or utc_timestamp(),
        score_before=score_before,
        score_after=score_after,
        delta=compute_delta(score_before, score_after),
        status=status,
        description=description,
    )


def append_entry(entry: ExperimentLogEntry, path: Path | None = None) -> None:
    """Append one experiment row, creating the TSV and header on first write."""
    resolved_path = path or default_log_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not resolved_path.exists() or resolved_path.stat().st_size == 0
    with resolved_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPERIMENT_LOG_HEADER, delimiter="\t")
        if should_write_header:
            writer.writeheader()
        writer.writerow(entry.to_row())


def read_entries(path: Path | None = None) -> list[ExperimentLogEntry]:
    """Read the TSV source of truth into typed entries for display logic."""
    resolved_path = path or default_log_path()
    if not resolved_path.exists() or resolved_path.stat().st_size == 0:
        return []

    with resolved_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [
            ExperimentLogEntry(
                cycle=int(row["cycle"]),
                timestamp=row["timestamp"],
                score_before=_parse_float(row.get("score_before", "")),
                score_after=_parse_float(row.get("score_after", "")),
                delta=_parse_float(row.get("delta", "")),
                status=row["status"],
                description=row.get("description", ""),
            )
            for row in reader
        ]


def next_cycle_number(path: Path | None = None) -> int:
    """Continue the experiment counter across optimize runs for coherent history."""
    entries = read_entries(path)
    if not entries:
        return 1
    return entries[-1].cycle + 1


def tail_entries(entries: list[ExperimentLogEntry], tail: int | None) -> list[ExperimentLogEntry]:
    """Apply tailing after parsing so all output modes share the same selection logic."""
    if tail is None or tail <= 0 or tail >= len(entries):
        return entries
    return entries[-tail:]


def format_table(entries: list[ExperimentLogEntry]) -> str:
    """Render aligned columns so humans can scan experiment history quickly."""
    headers = {
        "cycle": "cycle",
        "timestamp": "timestamp",
        "score_before": "score_before",
        "score_after": "score_after",
        "delta": "delta",
        "status": "status",
        "description": "description",
    }
    rows = [
        {
            "cycle": str(entry.cycle),
            "timestamp": entry.timestamp,
            "score_before": _format_display_score(entry.score_before),
            "score_after": _format_display_score(entry.score_after),
            "delta": _format_display_delta(entry.delta),
            "status": entry.status,
            "description": entry.description,
        }
        for entry in entries
    ]
    widths = {
        column: max(
            len(headers[column]),
            *(len(row[column]) for row in rows),
        )
        for column in headers
    }

    lines = [
        "  ".join(headers[column].ljust(widths[column]) for column in headers),
        "  ".join("-" * widths[column] for column in headers),
    ]
    for row in rows:
        status_text = row["status"].ljust(widths["status"])
        styled_status = click.style(status_text, fg=STATUS_COLORS.get(row["status"]))
        line = "  ".join(
            [
                row["cycle"].ljust(widths["cycle"]),
                row["timestamp"].ljust(widths["timestamp"]),
                row["score_before"].rjust(widths["score_before"]),
                row["score_after"].rjust(widths["score_after"]),
                row["delta"].rjust(widths["delta"]),
                styled_status,
                row["description"].ljust(widths["description"]),
            ]
        )
        lines.append(line)
    return "\n".join(lines)


def summarize_entries(entries: list[ExperimentLogEntry]) -> str:
    """Compress the log into one line for quick status checks and scripting."""
    counts = Counter(entry.status for entry in entries)
    count_parts = [
        f"{counts.get('keep', 0)} kept",
        f"{counts.get('discard', 0)} discarded",
        f"{counts.get('skip', 0)} skipped",
    ]
    if counts.get("crash", 0):
        count_parts.append(f"{counts['crash']} crashed")

    best_entry = best_score_entry(entries)
    latest_entry = latest_scored_entry(entries)
    summary = f"{len(entries)} experiments: {', '.join(count_parts)}."

    if best_entry is None:
        return f"{summary} Best: n/a. Latest: n/a"

    first_score = first_reference_score(entries)
    best_delta = best_entry.score_after - first_score if first_score is not None and best_entry.score_after is not None else None
    best_text = (
        f"Best: {best_entry.score_after:.2f} (cycle {best_entry.cycle}, {_signed_two_decimals(best_delta)} from first)"
        if best_entry.score_after is not None and best_delta is not None
        else f"Best: {best_entry.score_after:.2f} (cycle {best_entry.cycle})"
    )

    if latest_entry is None or latest_entry.score_after is None:
        return f"{summary} {best_text}. Latest: n/a"
    latest_text = f"Latest: {latest_entry.score_after:.2f} (cycle {latest_entry.cycle})"
    return f"{summary} {best_text}. {latest_text}"


def best_score_entry(entries: list[ExperimentLogEntry]) -> ExperimentLogEntry | None:
    """Find the best scored experiment for summaries and Ctrl+C reporting."""
    scored_entries = [entry for entry in entries if entry.score_after is not None]
    if not scored_entries:
        return None
    return max(scored_entries, key=lambda entry: entry.score_after)


def latest_scored_entry(entries: list[ExperimentLogEntry]) -> ExperimentLogEntry | None:
    """Report the most recent experiment that actually produced a score."""
    for entry in reversed(entries):
        if entry.score_after is not None:
            return entry
    return None


def first_reference_score(entries: list[ExperimentLogEntry]) -> float | None:
    """Use the earliest available baseline so the best-score delta is meaningful."""
    for entry in entries:
        if entry.score_before is not None:
            return entry.score_before
        if entry.score_after is not None:
            return entry.score_after
    return None


def _sanitize_text(value: str) -> str:
    """Collapse control characters so descriptions remain one TSV record per cycle."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _format_tsv_number(value: float | None) -> str:
    """Store numeric values with stable precision while keeping blanks for missing data."""
    if value is None:
        return ""
    return f"{value:.4f}"


def _parse_float(value: str | None) -> float | None:
    """Parse optional numeric TSV cells into floats."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def _format_display_score(value: float | None) -> str:
    """Display scores at human-readable precision without losing missingness."""
    if value is None:
        return "-"
    return f"{value:.2f}"


def _format_display_delta(value: float | None) -> str:
    """Display score deltas with an explicit sign so outcomes are easy to scan."""
    if value is None:
        return "-"
    return f"{value:+.2f}"


def _signed_two_decimals(value: float | None) -> str:
    """Format signed delta text for one-line summaries."""
    if value is None:
        return "n/a"
    return f"{value:+.2f}"
