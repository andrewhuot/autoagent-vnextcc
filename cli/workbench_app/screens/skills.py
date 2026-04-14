"""Full-screen skills menu (``/skills``).

Scaffold for T13: mirrors Claude Code's ``SkillsMenu`` — a navigable list of
installed skills plus action keys ``l`` (list), ``s`` (show), ``a`` (add),
``e`` (edit), ``r`` (remove). The actual behavior delegating to
:mod:`cli.skills` lands with T13; this module fixes the contract the wrapping
:class:`cli.workbench_app.commands.LocalJSXCommand` will rely on and lets the
screen render a non-trivial view today.

``SkillItem`` is a small typed record so callers can pass either real
``SkillRecord`` instances (via an adapter) or test fixtures without the
screen caring which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import click  # noqa: F401

from cli.workbench_app import theme
from cli.workbench_app.screens.base import (
    ACTION_EXIT,
    EchoFn,
    KeyProvider,
    Screen,
    ScreenResult,
)


SKILLS_ACTIONS: tuple[str, ...] = ("list", "show", "add", "edit", "remove")
"""Ordered action verbs surfaced in the footer hint."""


_UP_KEYS = frozenset({"k", "up"})
_DOWN_KEYS = frozenset({"j", "down"})
_CANCEL_KEYS = frozenset({"q", "escape", "ctrl+c"})

_ACTION_KEYS = {
    "l": "list",
    "s": "show",
    "a": "add",
    "e": "edit",
    "r": "remove",
}


@dataclass(frozen=True)
class SkillItem:
    """Minimal view model for a row in the skills menu."""

    skill_id: str
    name: str = ""
    kind: str = ""
    description: str = ""


def _format_row(item: SkillItem, *, selected: bool) -> str:
    display_name = item.name or item.skill_id
    kind = f"[{item.kind}] " if item.kind else ""
    line = f"  {kind}{display_name}"
    if item.description:
        line = f"{line} — {item.description}"
    if selected:
        return theme.workspace(f"▶{line[1:]}")
    return line


class SkillsScreen(Screen):
    """Arrow-key navigable list of skills plus action-key dispatch."""

    name = "skills"
    title = "/skills"

    def __init__(
        self,
        items: Sequence[SkillItem] | None = None,
        *,
        keys: KeyProvider | Iterable[str] | None = None,
        echo: EchoFn | None = None,
    ) -> None:
        super().__init__(keys=keys, echo=echo)
        self._items: list[SkillItem] = list(items or ())
        self._cursor = 0 if self._items else -1

    # ------------------------------------------------------------------ api

    @property
    def items(self) -> tuple[SkillItem, ...]:
        return tuple(self._items)

    @property
    def cursor(self) -> int:
        return self._cursor

    def selected(self) -> SkillItem | None:
        if self._cursor < 0 or self._cursor >= len(self._items):
            return None
        return self._items[self._cursor]

    def render_lines(self) -> list[str]:
        if not self._items:
            return [theme.meta("  (no skills installed)")]
        return [
            _format_row(item, selected=(i == self._cursor))
            for i, item in enumerate(self._items)
        ]

    def footer_lines(self) -> list[str]:
        hint = "  [j/k navigate · l list · s show · a add · e edit · r remove · q exit]"
        return ["", theme.meta(hint)]

    def handle_key(self, key: str) -> ScreenResult | None:
        if key in _CANCEL_KEYS:
            return ScreenResult(action=ACTION_EXIT)

        if key in _UP_KEYS and self._items:
            self._cursor = max(0, self._cursor - 1)
            return None
        if key in _DOWN_KEYS and self._items:
            self._cursor = min(len(self._items) - 1, self._cursor + 1)
            return None

        action = _ACTION_KEYS.get(key)
        if action is None:
            return None

        selected = self.selected()
        value = selected.skill_id if selected and action in {"show", "edit", "remove"} else None
        # ``list`` and ``add`` don't need a selection; pass ``None``.
        return ScreenResult(action=action, value=value)


__all__ = [
    "SKILLS_ACTIONS",
    "SkillItem",
    "SkillsScreen",
]
