"""Shared help text for Workbench prompt affordances.

The shortcut reference rendered by both the bare ``?`` prompt and the
``/shortcuts`` slash command lives here so every surface stays in sync.
We deliberately keep this module dependency-light — no slash-command
registry imports — because it is consumed during the prompt banner
render, long before the registry is built.
"""

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
            ShortcutHelpItem("ctrl-t", "Toggle collapsed transcript view"),
            ShortcutHelpItem("shift+tab", "Cycle visible permission modes"),
        ),
    ),
    (
        "Discover",
        (
            ShortcutHelpItem("/help", "Browsable help with categories + filter"),
            ShortcutHelpItem("/help <query>", "Fuzzy-match commands by name or keyword"),
            ShortcutHelpItem("/find <query>", "Quick-open across commands, sessions, memories"),
            ShortcutHelpItem("/keybindings", "Inspect active keyboard bindings"),
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
    """Return the short user-facing shortcut reference.

    Columns are sized to the longest key cell so each group lines up even
    when a later group introduces a longer shortcut (e.g. ``/help <query>``
    vs ``enter``). Claude Code's ``/shortcuts`` surface reads as a tidy
    two-column list and the alignment is what sells the "polished" feel.
    """

    key_width = max(
        len(item.key)
        for _group, items in _SHORTCUT_GROUPS
        for item in items
    )
    lines = [theme.heading("\n  Workbench Shortcuts")]
    for group_name, items in _SHORTCUT_GROUPS:
        lines.append(theme.meta(f"  {group_name}"))
        for item in items:
            padded = item.key.ljust(key_width)
            lines.append(f"    {padded}  {item.action}")
    lines.append("")
    lines.append(
        "  Type /help for the full command palette, /find <query> to search, "
        "/keybindings to inspect key bindings."
    )
    return "\n".join(lines)


__all__ = ["ShortcutHelpItem", "render_shortcuts_help"]
