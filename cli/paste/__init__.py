"""Paste storage helpers."""

from .placeholders import expand_placeholders, render_placeholder
from .store import PasteHandle, PasteStore

__all__ = [
    "PasteHandle",
    "PasteStore",
    "expand_placeholders",
    "render_placeholder",
]
