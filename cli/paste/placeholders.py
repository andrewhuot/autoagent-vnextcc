"""Placeholder rendering and expansion for stored pastes."""

from __future__ import annotations

import re

from cli.paste.store import PasteHandle, PasteStore


_PLACEHOLDER_RE = re.compile(r"\[Pasted text #(?P<number>\d+) \+\d+ lines\]")


def render_placeholder(handle: PasteHandle) -> str:
    """Render the compact placeholder shown in the prompt."""
    extra_lines = max(handle.line_count - 1, 0)
    return f"[Pasted text #{handle.display_number} +{extra_lines} lines]"


def expand_placeholders(text: str, store: PasteStore) -> str:
    """Replace visible placeholders with their full stored content."""

    def _replace(match: re.Match[str]) -> str:
        return store.load_by_display_number(int(match.group("number")))

    return _PLACEHOLDER_RE.sub(_replace, text)
