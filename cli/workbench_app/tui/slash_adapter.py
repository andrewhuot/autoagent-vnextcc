"""Bridge between the TUI input and the existing slash dispatch system.

Constructs a :class:`~cli.workbench_app.slash.SlashContext` whose ``echo``
function routes output through the centralized :class:`Store` rather than
``click.echo``. All existing slash handlers work unchanged because they
accept ``(ctx, *args)`` and return ``OnDoneResult | str | None``.
"""

from __future__ import annotations

from typing import Any

from cli.sessions import Session, SessionStore
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.help_text import render_shortcuts_help
from cli.workbench_app.input_router import InputKind, InputRoute, route_user_input
from cli.workbench_app.slash import DispatchResult, SlashContext, dispatch
from cli.workbench_app.store import AppState, Store, append_message
from cli.workbench_app.transcript import TranscriptRole


__all__ = [
    "TUISlashAdapter",
]


class TUISlashAdapter:
    """Adapts slash dispatch for the TUI, routing output through the store.

    Usage::

        adapter = TUISlashAdapter(store, workspace=workspace)
        adapter.handle_input("/help")
    """

    def __init__(
        self,
        store: Store[AppState],
        *,
        workspace: Any | None = None,
        session: Session | None = None,
        session_store: SessionStore | None = None,
        registry: CommandRegistry | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._cancellation = CancellationToken()
        self._ctx = SlashContext(
            workspace=workspace,
            session=session,
            session_store=session_store,
            echo=self._store_echo,
            registry=registry,
            cancellation=self._cancellation,
        )

    @property
    def context(self) -> SlashContext:
        return self._ctx

    @property
    def registry(self) -> CommandRegistry | None:
        return self._registry

    def _store_echo(self, text: str) -> None:
        """Echo function that routes output to the store as a system message."""
        self._store.set_state(append_message("system", text))

    def handle_input(self, raw: str) -> InputRoute:
        """Route and handle a raw input line.

        Returns the :class:`InputRoute` so the caller can inspect the
        classification (e.g. to handle EXIT or CHAT differently).
        """
        route = route_user_input(raw)

        if route.kind == InputKind.EMPTY:
            return route

        if route.kind == InputKind.EXIT:
            return route

        if route.kind == InputKind.SHORTCUTS:
            help_text = render_shortcuts_help()
            self._store.set_state(append_message("system", help_text))
            return route

        if route.kind == InputKind.SHELL:
            self._store.set_state(append_message(
                "warning",
                "Shell mode (!command) requires a terminal. Use /exit and run the command directly.",
            ))
            return route

        if route.kind == InputKind.BACKGROUND:
            self._store.set_state(append_message(
                "meta",
                "Background execution (&command) is not yet supported in the TUI.",
            ))
            return route

        if route.kind == InputKind.SLASH:
            # Echo the user command first.
            self._store.set_state(append_message("user", raw.strip()))
            result = self._dispatch_slash(route)
            if result.exit:
                # Propagate exit request back to the route.
                return InputRoute(
                    kind=InputKind.EXIT,
                    raw=route.raw,
                    payload=route.payload,
                )
            return route

        if route.kind == InputKind.CHAT:
            # Echo the user message. The orchestrator turn will be wired
            # in Phase 3 — for now just acknowledge.
            self._store.set_state(append_message("user", raw.strip()))
            self._store.set_state(append_message(
                "meta",
                "Chat mode requires a configured model. Use /help for available commands.",
            ))
            return route

        return route

    def _dispatch_slash(self, route: InputRoute) -> DispatchResult:
        """Dispatch a slash command through the existing registry."""
        if self._registry is None:
            self._store.set_state(append_message(
                "error",
                "No command registry available.",
            ))
            return DispatchResult(handled=False)

        return dispatch(self._ctx, route.payload, registry=self._registry)
