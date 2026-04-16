"""Textual TUI application for the AgentLab workbench.

Entry point: :func:`run_tui_app`, called from ``launch_workbench()`` in
``cli/workbench_app/app.py`` when ``AGENTLAB_TUI=1`` is set.

The app mounts a reactive widget tree driven by a centralized
:class:`~cli.workbench_app.store.Store`. Coordinator events flow through
:class:`~cli.workbench_app.store_bridge.EventStoreAdapter` into the store,
and widgets subscribe to the slices they care about.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from textual.app import App, ComposeResult

from cli.workbench_app.store import AppState, Store, append_message, get_default_app_state
from cli.workbench_app.tui.widgets.background_panel import BackgroundPanel
from cli.workbench_app.tui.widgets.coordinator_panel import CoordinatorPanel
from cli.workbench_app.tui.widgets.effort_indicator_widget import EffortIndicatorWidget
from cli.workbench_app.tui.widgets.input_area import InputArea
from cli.workbench_app.tui.widgets.message_list import MessageList
from cli.workbench_app.tui.widgets.status_footer import StatusFooter
from cli.workbench_app.tui.widgets.streaming_message import StreamingMessage
from cli.workbench_app.tui.widgets.welcome_card import WelcomeCard


CSS_PATH = Path(__file__).parent / "styles" / "default.tcss"


class WorkbenchTUIApp(App):
    """Main Textual application for the AgentLab workbench.

    Widget hierarchy::

        WorkbenchTUIApp
          +-- WelcomeCard
          +-- MessageList (scrollable, flex-grow)
          +-- CoordinatorPanel (auto-height, hidden when idle)
          +-- StreamingMessage (auto-height, hidden when not streaming)
          +-- EffortIndicatorWidget (1 row, hidden when idle)
          +-- BackgroundPanel (auto-height, hidden when no tasks)
          +-- InputArea (dock bottom)
          +-- StatusFooter (dock bottom)
    """

    TITLE = "AgentLab Workbench"
    CSS_PATH = str(Path(__file__).parent / "styles" / "default.tcss")

    BINDINGS = [
        ("ctrl+c", "interrupt", "Interrupt"),
        ("shift+tab", "cycle_mode", "Cycle permission mode"),
    ]

    # Permission mode cycle (matches pt_prompt.py PROMPT_PERMISSION_MODE_CYCLE).
    _MODE_CYCLE = ("default", "acceptEdits", "plan", "bypass")

    def __init__(
        self,
        store: Store[AppState] | None = None,
        *,
        slash_adapter: Any | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._store = store or Store(get_default_app_state())
        self._slash_adapter = slash_adapter
        self._last_interrupt: float = 0.0
        self._theme_unsub: Any = None

    @property
    def store(self) -> Store[AppState]:
        return self._store

    def _on_theme_changed(self) -> None:
        """Watch store for theme changes and swap CSS."""
        theme_name = self._store.get_state().theme_name
        self.switch_theme(theme_name)

    def switch_theme(self, name: str) -> None:
        """Switch the TUI theme by loading a different CSS file."""
        styles_dir = Path(__file__).parent / "styles"
        css_file = styles_dir / f"{name}.tcss"
        if not css_file.exists():
            css_file = styles_dir / "default.tcss"
        try:
            css_text = css_file.read_text()
            self.stylesheet.parse(css_text, path=str(css_file))
            self.stylesheet.reparse()
            self.refresh(layout=True)
        except Exception:
            logger.debug("Failed to switch theme to %s", name, exc_info=True)

    def compose(self) -> ComposeResult:
        yield WelcomeCard(self._store)
        yield MessageList(self._store)
        yield CoordinatorPanel(self._store)
        yield StreamingMessage(self._store)
        yield EffortIndicatorWidget(self._store)
        yield BackgroundPanel(self._store)
        # StatusFooter docks to bottom, then InputArea docks above it.
        yield StatusFooter(self._store)
        yield InputArea(self._store, slash_adapter=self._slash_adapter)

    def on_mount(self) -> None:
        # Focus the input on startup.
        input_area = self.query_one(InputArea)
        input_widget = input_area.query_one("Input")
        if input_widget is not None:
            input_widget.focus()

    def action_interrupt(self) -> None:
        """Double ctrl+c to exit, matching legacy REPL semantics."""
        now = time.monotonic()
        if now - self._last_interrupt < 2.0:
            self.exit()
        else:
            self._last_interrupt = now
            self._store.set_state(append_message(
                "warning",
                "(press ctrl+c again to exit, or /exit)",
            ))

    def action_cycle_mode(self) -> None:
        """Cycle permission mode via shift+tab."""
        from cli.workbench_app.transcript import TranscriptEntry

        state = self._store.get_state()
        current = state.permission_mode
        try:
            idx = self._MODE_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_mode = self._MODE_CYCLE[(idx + 1) % len(self._MODE_CYCLE)]
        entry = TranscriptEntry(role="meta", content=f"Permission mode: {next_mode}")
        self._store.set_state(lambda s: replace(
            s,
            permission_mode=next_mode,
            messages=s.messages + (entry,),
        ))


def _populate_store_from_workspace(
    store: Store[AppState],
    workspace: Any | None,
) -> None:
    """Read workspace state and push it into the store."""
    if workspace is None:
        return

    from cli.workbench_app.status_bar import snapshot_from_workspace

    snap = snapshot_from_workspace(workspace)
    store.set_state(lambda s: replace(
        s,
        workspace_label=snap.workspace_label,
        config_version=snap.config_version,
        model=snap.model,
        provider=snap.provider,
        provider_key_present=snap.provider_key_present,
        pending_reviews=snap.pending_reviews,
        best_score=snap.best_score,
        agentlab_version=snap.agentlab_version,
        session_title=snap.session_title,
        tokens_used=snap.tokens_used,
        context_limit=snap.context_limit,
    ))


def run_tui_app(
    workspace: Any | None = None,
    *,
    show_banner: bool = True,
    echo: Any | None = None,
) -> Any:
    """Create and run the Textual TUI app.

    Returns a ``StubAppResult``-compatible object for the legacy interface.
    """
    from cli.workbench_app.app import StubAppResult

    # Build the store and populate from workspace.
    store = Store(get_default_app_state())

    # Get version.
    try:
        from cli.branding import get_agentlab_version
        version = get_agentlab_version()
    except Exception:
        version = "dev"
    store.set_state(lambda s: replace(s, agentlab_version=version))

    # Read workspace state.
    _populate_store_from_workspace(store, workspace)

    # Read permission mode.
    try:
        from cli.permissions import PermissionManager
        root = getattr(workspace, "root", None)
        mode = PermissionManager(root=root).mode
        store.set_state(lambda s: replace(s, permission_mode=mode))
    except Exception:
        logger.debug("Could not read permission mode", exc_info=True)

    # Build slash adapter with command registry.
    slash_adapter = None
    try:
        from cli.workbench_app.slash import build_builtin_registry
        from cli.workbench_app.tui.slash_adapter import TUISlashAdapter

        registry = build_builtin_registry()
        slash_adapter = TUISlashAdapter(
            store,
            workspace=workspace,
            registry=registry,
        )
    except Exception:
        logger.warning("Could not build slash adapter", exc_info=True)

    app = WorkbenchTUIApp(store=store, slash_adapter=slash_adapter)
    app.run()

    return StubAppResult(lines_read=0, exited_via="tui")
