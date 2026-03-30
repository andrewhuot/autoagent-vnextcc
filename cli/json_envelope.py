"""Standard JSON envelope helpers for CLI machine output."""

from __future__ import annotations

import json
from typing import Any


API_VERSION = "1"


def render_json_envelope(status: str, data: Any, next_command: str | None = None) -> str:
    """Render the standard CLI JSON envelope."""
    envelope: dict[str, Any] = {
        "api_version": API_VERSION,
        "status": status,
        "data": data,
    }
    if next_command:
        envelope["next"] = next_command
    return json.dumps(envelope, indent=2, default=str)
