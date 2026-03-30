"""Shared output helpers for human, JSON, and stream-JSON CLI surfaces."""

from __future__ import annotations

import json
from typing import Any, Callable

import click

from cli.json_envelope import render_json_envelope


OUTPUT_FORMATS = ("text", "json", "stream-json")


def resolve_output_format(output_format: str | None, *, json_output: bool = False) -> str:
    """Resolve the effective output format from legacy and new flags."""
    if json_output:
        return "json"
    normalized = (output_format or "text").strip().lower()
    if normalized not in OUTPUT_FORMATS:
        raise click.ClickException(
            "Unsupported output format. Choose one of: text, json, stream-json."
        )
    return normalized


def emit_json_envelope(
    status: str,
    data: Any,
    *,
    next_command: str | None = None,
    writer: Callable[[str], None] | None = None,
) -> str:
    """Render and optionally emit the standard JSON envelope."""
    payload = render_json_envelope(status=status, data=data, next_command=next_command)
    if writer is not None:
        writer(payload)
    return payload


def emit_stream_json(event: dict[str, Any], *, writer: Callable[[str], None] | None = None) -> str:
    """Render a single stream-json line and optionally emit it."""
    line = json.dumps(event, default=str)
    if writer is not None:
        writer(line)
    return line
