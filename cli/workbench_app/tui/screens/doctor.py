"""Doctor diagnostic screen for the TUI workbench.

Port of ``cli.workbench_app.screens.doctor.DoctorScreen`` — the
synchronous key loop is replaced by a Textual screen with scrollable
content and key bindings.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import Static

from cli.workbench_app.screens.base import ACTION_EXIT, ScreenResult
from cli.workbench_app.tui.screens.base import TUIScreen


class DoctorScreen(TUIScreen):
    """Full-screen diagnostic view showing workspace health.

    Runs the same diagnostic checks as ``/doctor`` but in a scrollable
    full-screen layout. Press ``q`` or ``Esc`` to return.
    """

    screen_title = "/doctor — Workspace Diagnostics"

    def __init__(
        self,
        workspace: Any | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._workspace = workspace

    def screen_content(self) -> ComposeResult:
        diagnostics = self._run_diagnostics()
        for line in diagnostics:
            yield Static(line)

    def hint_text(self) -> str:
        return "Press [q] or [Esc] to close"

    def _run_diagnostics(self) -> list[str]:
        """Gather diagnostic lines from the workspace."""
        lines: list[str] = []

        if self._workspace is None:
            lines.append("[yellow]No workspace active[/]")
            lines.append("")
            lines.append("Run [bold]agentlab init[/] to create a workspace,")
            lines.append("or [bold]cd[/] into an existing workspace directory.")
            return lines

        lines.append(f"[bold]Workspace:[/] {getattr(self._workspace, 'root', '?')}")
        lines.append("")

        # Check config
        try:
            config = self._workspace.resolve_active_config()
            if config:
                lines.append(f"[green]\u2713[/] Active config found")
            else:
                lines.append(f"[yellow]\u26a0[/] No active config")
        except Exception as e:
            lines.append(f"[red]\u2717[/] Config error: {e}")

        # Check model
        lines.append("")
        lines.append("[bold]Model Configuration:[/]")
        try:
            import os
            for key in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
                if os.environ.get(key):
                    lines.append(f"  [green]\u2713[/] {key} is set")
                else:
                    lines.append(f"  [dim]\u2013[/] {key} not set")
        except Exception:
            lines.append("  [red]\u2717[/] Could not check environment")

        lines.append("")
        lines.append("[bold]Session:[/]")
        lines.append("  Use [bold]/status[/] for session details")

        # Settings cascade + hook registry. Wrapped so a settings load
        # failure cannot crash the diagnostic screen.
        try:
            from pathlib import Path as _Path

            from cli.doctor_sections import (
                render_hooks_section,
                render_settings_section,
            )
            from cli.hooks import HookRegistry
            from cli.settings import load_settings

            root = getattr(self._workspace, "root", None) or _Path.cwd()
            try:
                settings_obj = load_settings(root)
            except Exception:
                settings_obj = None

            for line in render_settings_section(settings_obj):
                lines.append(line)

            try:
                registry = (
                    HookRegistry.load_from_settings(settings_obj)
                    if settings_obj is not None
                    else HookRegistry()
                )
            except Exception as exc:
                registry = HookRegistry()
                registry.load_errors = [f"hook load failed: {exc}"]  # type: ignore[attr-defined]
            for line in render_hooks_section(registry):
                lines.append(line)
        except Exception as exc:  # pragma: no cover - defensive
            lines.append("")
            lines.append(f"[yellow]Settings/Hooks diagnostics failed: {exc}[/]")

        return lines
