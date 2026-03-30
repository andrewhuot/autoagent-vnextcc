"""Shared CLI recovery and doctor-routing helpers."""

from __future__ import annotations

from typing import Any

import click


DOCTOR_COMMAND = "autoagent doctor"


def with_doctor_hint(message: str, *, doctor_command: str = DOCTOR_COMMAND) -> str:
    """Append the shared doctor recovery hint to a user-facing error."""
    stripped = message.rstrip()
    return f"{stripped}\nTry next: {doctor_command}"


def click_error(message: str, *, doctor_command: str = DOCTOR_COMMAND) -> click.ClickException:
    """Create a click error with the shared doctor hint."""
    return click.ClickException(with_doctor_hint(message, doctor_command=doctor_command))


def recovery_payload(
    *,
    what_failed: str,
    why_likely: str | None = None,
    try_next: list[str] | None = None,
    doctor_command: str = DOCTOR_COMMAND,
    docs_link: str | None = None,
) -> dict[str, Any]:
    """Build a structured recovery payload for JSON command surfaces."""
    next_steps = list(try_next or [])
    if doctor_command not in next_steps:
        next_steps.append(doctor_command)
    payload: dict[str, Any] = {
        "what_failed": what_failed,
        "try_next": next_steps,
    }
    if why_likely:
        payload["why_likely"] = why_likely
    if docs_link:
        payload["docs_link"] = docs_link
    return payload
