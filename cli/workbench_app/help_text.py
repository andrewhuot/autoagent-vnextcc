"""Shared help text for Workbench prompt affordances."""

from __future__ import annotations

from dataclasses import dataclass

from cli.workbench_app import theme


@dataclass(frozen=True)
class ShortcutHelpItem:
    """One keyboard or input prefix shortcut shown in Workbench help."""

    key: str
    action: str


_SHORTCUT_GROUPS: tuple[tuple[str, tuple[ShortcutHelpItem, ...]], ...] = (
    (
        "Input",
        (
            ShortcutHelpItem("/ for commands", "Open slash command completion"),
            ShortcutHelpItem("? for shortcuts", "Show this shortcut reference"),
            ShortcutHelpItem("enter", "Submit the current prompt"),
        ),
    ),
    (
        "Control",
        (
            ShortcutHelpItem("ctrl-c", "Cancel active work, then press again to exit"),
            ShortcutHelpItem("ctrl-d", "Exit on EOF"),
            ShortcutHelpItem("shift+tab", "Cycle visible permission modes"),
        ),
    ),
    (
        "Sessions",
        (
            ShortcutHelpItem("/sessions", "List recent saved sessions"),
            ShortcutHelpItem("/resume [id]", "Resume the latest or selected session"),
            ShortcutHelpItem("/new [title]", "Start a fresh session"),
        ),
    ),
)


def render_shortcuts_help() -> str:
    """Return the short user-facing shortcut reference."""

    lines = [theme.heading("\n  Workbench Shortcuts")]
    for group_name, items in _SHORTCUT_GROUPS:
        lines.append(theme.meta(f"  {group_name}"))
        for item in items:
            lines.append(f"    {item.key:<18} {item.action}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["ShortcutHelpItem", "render_shortcuts_help"]
