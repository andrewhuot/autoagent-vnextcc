"""Structured diff helper + widget for file-editing tool results."""

from __future__ import annotations

import difflib
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.widget import Widget


STRUCTURED_DIFF_CACHE_MAX = 64
_SIDE_BY_SIDE_MIN_WIDTH = 80
_DIFF_CACHE: OrderedDict[tuple[str, str, str | None, int], tuple["DiffRow", ...]] = OrderedDict()


@dataclass(frozen=True)
class DiffRow:
    """One render-ready diff row.

    ``text`` is used for unified rows and binary fallbacks. ``left_text`` /
    ``right_text`` back the side-by-side layout. Line numbers stay optional so
    callers can render context rows and file additions with the same shape.
    """

    layout: Literal["side_by_side", "unified"]
    kind: Literal["context", "delete", "insert", "replace", "header", "binary"]
    text: str = ""
    left_text: str = ""
    right_text: str = ""
    left_line_no: int | None = None
    right_line_no: int | None = None


def clear_diff_cache() -> None:
    """Drop the in-memory diff cache."""
    _DIFF_CACHE.clear()


def diff_cache_size() -> int:
    """Expose the current cache size for tests."""
    return len(_DIFF_CACHE)


def build_diff_lines(
    old: str,
    new: str,
    *,
    language: str | None,
    width: int,
) -> list[DiffRow]:
    """Build width-aware diff rows with an LRU cache."""
    key = (_sha256(old), _sha256(new), language, width)
    cached = _DIFF_CACHE.get(key)
    if cached is not None:
        _DIFF_CACHE.move_to_end(key)
        return list(cached)

    if _looks_binary(old) or _looks_binary(new):
        rows = [DiffRow(layout="unified", kind="binary", text="Binary content changed.")]
    elif width < _SIDE_BY_SIDE_MIN_WIDTH:
        rows = _build_unified_rows(old, new)
    else:
        rows = _build_side_by_side_rows(old, new)

    _DIFF_CACHE[key] = tuple(rows)
    _DIFF_CACHE.move_to_end(key)
    while len(_DIFF_CACHE) > STRUCTURED_DIFF_CACHE_MAX:
        _DIFF_CACHE.popitem(last=False)
    return list(rows)


class StructuredDiff(Widget):
    """Render a structured diff with a side-by-side wide layout."""

    DEFAULT_CSS = """
    StructuredDiff {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        old: str,
        new: str,
        language: str | None,
        width: int | None = 120,
        file_path: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._old = old
        self._new = new
        self._language = language
        self._file_path = file_path
        self._width_override = width
        self._resolved_width = self._normalize_width(width)
        self.rows = build_diff_lines(
            old,
            new,
            language=language,
            width=self._resolved_width,
        )

    def update_diff(
        self,
        *,
        old: str,
        new: str,
        language: str | None,
        width: int | None,
        file_path: str | None = None,
    ) -> None:
        """Replace the diff payload and refresh when mounted."""
        self._old = old
        self._new = new
        self._language = language
        self._file_path = file_path
        self._width_override = width
        self._resolved_width = self._normalize_width(width)
        self.rows = build_diff_lines(
            old,
            new,
            language=language,
            width=self._resolved_width,
        )
        self._refresh_if_mounted()

    def render(self) -> Any:
        if not self.rows:
            return Text("")
        body: Any
        if self.rows[0].layout == "unified":
            body = _render_unified_rows(self.rows, language=self._language)
        else:
            body = _render_side_by_side_rows(self.rows, language=self._language)
        header = _render_header(self._file_path, self.rows[0].layout)
        if header is None:
            return body
        return Group(header, body)

    def on_mount(self) -> None:
        if self._width_override is None:
            self.update_width(self.size.width)

    def on_resize(self, _event: Any) -> None:
        if self._width_override is None:
            self.update_width(self.size.width)

    def update_width(self, width: int | None) -> None:
        """Reflow the diff for the available width when the layout changes."""
        normalized = self._normalize_width(width)
        if normalized == self._resolved_width:
            return
        self._resolved_width = normalized
        self.rows = build_diff_lines(
            self._old,
            self._new,
            language=self._language,
            width=self._resolved_width,
        )
        self._refresh_if_mounted()

    def _refresh_if_mounted(self) -> None:
        if self.is_mounted:
            self.refresh(layout=True)

    def _normalize_width(self, width: int | None) -> int:
        if width is None:
            return max(self.size.width, 1) if self.size.width else 120
        return max(width, 1)


def _build_unified_rows(old: str, new: str) -> list[DiffRow]:
    diff = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    rows: list[DiffRow] = []
    for line in diff:
        kind = "context"
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            kind = "header"
        elif line.startswith("-") and not line.startswith("---"):
            kind = "delete"
        elif line.startswith("+") and not line.startswith("+++"):
            kind = "insert"
        rows.append(DiffRow(layout="unified", kind=kind, text=line))
    return rows or [DiffRow(layout="unified", kind="context", text="(no visible changes)")]


def _build_side_by_side_rows(old: str, new: str) -> list[DiffRow]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    rows: list[DiffRow] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_chunk = old_lines[i1:i2]
        right_chunk = new_lines[j1:j2]
        total = max(len(left_chunk), len(right_chunk), 1)

        for offset in range(total):
            left_text = left_chunk[offset] if offset < len(left_chunk) else ""
            right_text = right_chunk[offset] if offset < len(right_chunk) else ""
            left_no = i1 + offset + 1 if offset < len(left_chunk) else None
            right_no = j1 + offset + 1 if offset < len(right_chunk) else None
            kind = tag if tag in {"replace", "delete", "insert"} else "context"
            rows.append(
                DiffRow(
                    layout="side_by_side",
                    kind=kind,
                    left_text=left_text,
                    right_text=right_text,
                    left_line_no=left_no,
                    right_line_no=right_no,
                    text=_side_by_side_text(left_text, right_text),
                )
            )
    return rows or [DiffRow(layout="side_by_side", kind="context", text="(no visible changes)")]


def _render_unified_rows(rows: list[DiffRow], *, language: str | None) -> Text:
    rendered = Text()
    for index, row in enumerate(rows):
        rendered.append(_highlight_line(row.text, language=language, style=_row_style(row.kind)))
        if index != len(rows) - 1:
            rendered.append("\n")
    return rendered


def _render_side_by_side_rows(rows: list[DiffRow], *, language: str | None) -> Table:
    left_gutter_width = max(len(str(row.left_line_no)) for row in rows if row.left_line_no is not None) if any(
        row.left_line_no is not None for row in rows
    ) else 1
    right_gutter_width = max(len(str(row.right_line_no)) for row in rows if row.right_line_no is not None) if any(
        row.right_line_no is not None for row in rows
    ) else 1

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="right", style="dim", no_wrap=True, width=left_gutter_width)
    table.add_column(ratio=1)
    table.add_column(justify="right", style="dim", no_wrap=True, width=right_gutter_width)
    table.add_column(ratio=1)

    for row in rows:
        table.add_row(
            Text("" if row.left_line_no is None else str(row.left_line_no), style="dim"),
            _highlight_line(row.left_text, language=language, style=_left_style(row.kind)),
            Text("" if row.right_line_no is None else str(row.right_line_no), style="dim"),
            _highlight_line(row.right_text, language=language, style=_right_style(row.kind)),
        )
    return table


def _render_header(file_path: str | None, layout: str) -> Text | None:
    if not file_path:
        return None
    label = "Unified diff" if layout == "unified" else "Structured diff"
    return Text(f"{label} · {file_path}", style="dim")


def _highlight_line(text: str, *, language: str | None, style: str | None = None) -> Text:
    if not text:
        return Text("", style=style or "")

    pygments = _load_pygments()
    if pygments is None or language is None:
        return Text(text, style=style or "")

    highlight, get_lexer_by_name, terminal_formatter, class_not_found = pygments
    try:
        lexer = get_lexer_by_name(language)
        ansi = highlight(text, lexer, terminal_formatter()).rstrip("\n")
        highlighted = Text.from_ansi(ansi)
        if style:
            highlighted.stylize(style)
        return highlighted
    except (class_not_found, Exception):
        return Text(text, style=style or "")


def _load_pygments() -> tuple[Any, Any, Any, Any] | None:
    """Lazily load pygments bits used for line highlighting."""
    try:
        from pygments import highlight
        from pygments.formatters import TerminalFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except Exception:
        return None
    return highlight, get_lexer_by_name, TerminalFormatter, ClassNotFound


def _looks_binary(text: str) -> bool:
    return "\x00" in text


def _side_by_side_text(left: str, right: str) -> str:
    return f"{left} | {right}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row_style(kind: str) -> str:
    if kind == "delete":
        return "red"
    if kind == "insert":
        return "green"
    if kind == "header":
        return "dim"
    return ""


def _left_style(kind: str) -> str:
    if kind in {"delete", "replace"}:
        return "red"
    return ""


def _right_style(kind: str) -> str:
    if kind in {"insert", "replace"}:
        return "green"
    return ""


__all__ = [
    "STRUCTURED_DIFF_CACHE_MAX",
    "DiffRow",
    "StructuredDiff",
    "build_diff_lines",
    "clear_diff_cache",
    "diff_cache_size",
]
