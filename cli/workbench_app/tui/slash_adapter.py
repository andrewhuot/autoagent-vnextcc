"""Bridge between the TUI input and the existing slash dispatch system.

Constructs a :class:`~cli.workbench_app.slash.SlashContext` whose ``echo``
function routes output through the centralized :class:`Store` rather than
``click.echo``. All existing slash handlers work unchanged because they
accept ``(ctx, *args)`` and return ``OnDoneResult | str | None``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from typing import Any, TYPE_CHECKING

from cli.sessions import Session, SessionStore
from cli.tools.rendering import iter_tool_display_payloads
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.help_text import render_shortcuts_help
from cli.workbench_app.input_router import InputKind, InputRoute, route_user_input
from cli.workbench_app.slash import DispatchResult, SlashContext, dispatch
from cli.workbench_app.store import AppState, Store, append_message
from cli.workbench_app.transcript import TranscriptRole

if TYPE_CHECKING:
    from textual.app import App

logger = logging.getLogger(__name__)


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
        orchestrator: Any | None = None,
        background_registry: Any | None = None,
        app: "App | None" = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._orchestrator = orchestrator
        self._background_registry = background_registry
        self._app = app
        self._cancellation = CancellationToken()
        self._turn_lock = threading.Lock()
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

    @property
    def orchestrator(self) -> Any | None:
        return self._orchestrator

    @orchestrator.setter
    def orchestrator(self, value: Any | None) -> None:
        self._orchestrator = value

    @property
    def app(self) -> "App | None":
        return self._app

    @app.setter
    def app(self, value: "App | None") -> None:
        self._app = value

    def _store_echo(self, text: str) -> None:
        """Echo function that routes output to the store as a system message."""
        self._store.set_state(append_message("system", text))

    # ------------------------------------------------------------------ chat

    def _run_orchestrator_turn(self, user_prompt: str) -> None:
        """Execute an LLM orchestrator turn in a background thread.

        Streams output into the store's ``streaming_content`` field so the
        ``StreamingMessage`` widget picks up deltas live. When the turn
        completes, the final assistant text is appended to the transcript
        and ``streaming_content`` is cleared.
        """
        orchestrator = self._orchestrator
        if orchestrator is None:
            return

        if not self._turn_lock.acquire(blocking=False):
            self._store.set_state(append_message(
                "warning", "An LLM turn is already in progress.",
            ))
            return

        acquired = True
        self._cancellation.reset()

        # Accumulator for the full assistant response.
        parts: list[str] = []

        def _streaming_echo(text: str) -> None:
            """Echo sink that routes deltas to the store for live rendering."""
            parts.append(text)
            content = "".join(parts)
            self._store.set_state(
                lambda s: replace(s, streaming_content=content)
            )

        previous_echo = getattr(orchestrator, "echo", None)
        previous_cancellation = getattr(orchestrator, "tool_cancellation", None)
        try:
            orchestrator.echo = _streaming_echo
        except Exception:
            previous_echo = None
        try:
            orchestrator.tool_cancellation = self._cancellation
        except Exception:
            previous_cancellation = None

        try:
            result = orchestrator.run_turn(user_prompt)
        except Exception as exc:
            logger.warning("Orchestrator turn failed", exc_info=True)
            self._store.set_state(append_message(
                "error", f"LLM turn failed: {exc}",
            ))
            return
        finally:
            if previous_echo is not None:
                try:
                    orchestrator.echo = previous_echo
                except Exception:
                    pass
            try:
                orchestrator.tool_cancellation = previous_cancellation
            except Exception:
                pass
            # Clear streaming state and unlock.
            self._store.set_state(
                lambda s: replace(s, streaming_content=None)
            )
            if acquired:
                self._turn_lock.release()

        # Append the final assistant message to the transcript.
        assistant_text = getattr(result, "assistant_text", "") or ""
        for payload in iter_tool_display_payloads(getattr(result, "tool_executions", []) or []):
            self._store.set_state(
                append_message(
                    "tool",
                    payload.display,
                    data={
                        "tool_name": payload.tool_name,
                        "renderable": payload.renderable,
                    },
                )
            )
        if assistant_text:
            self._store.set_state(append_message("assistant", assistant_text))

        stop_reason = getattr(result, "stop_reason", None)
        if stop_reason and stop_reason not in ("end_turn",):
            self._store.set_state(append_message(
                "meta", f"(stop: {stop_reason})",
            ))

    # ------------------------------------------------------------------ shell

    def _run_shell_command(self, command: str) -> None:
        """Execute a shell command by suspending the TUI."""
        app = self._app
        if app is None:
            self._store.set_state(append_message(
                "warning",
                "Shell mode (!command) requires a terminal. Use /exit and run the command directly.",
            ))
            return

        try:
            from textual.app import SuspendNotSupported
        except ImportError:
            SuspendNotSupported = type(None)  # type: ignore[misc,assignment]

        try:
            from cli.workbench_app.shell_mode import run_shell_turn
        except ImportError:
            self._store.set_state(append_message(
                "error", "Shell mode is not available (missing shell_mode module).",
            ))
            return

        workspace = self._ctx.workspace
        workspace_root = getattr(workspace, "root", None)
        permission_mode = self._store.get_state().permission_mode

        try:
            with app.suspend():
                run_shell_turn(
                    line=command,
                    workspace_root=workspace_root,
                    permission_mode=permission_mode,
                    echo=print,
                    input_provider=input,
                )
                # Pause so user can see output before TUI resumes.
                input("\n(press Enter to return to TUI)")
        except SuspendNotSupported:
            self._store.set_state(append_message(
                "warning",
                "Shell suspend is not supported in this terminal. Use /exit and run the command directly.",
            ))
        except Exception as exc:
            logger.warning("Shell command failed", exc_info=True)
            self._store.set_state(append_message(
                "error", f"Shell command failed: {exc}",
            ))

    # ------------------------------------------------------------------ background

    def _run_background_command(self, command: str) -> None:
        """Execute a command as a background task with registry tracking."""
        if self._orchestrator is None:
            self._store.set_state(append_message(
                "meta",
                "Background execution requires a configured model. Use /help for available commands.",
            ))
            return

        registry = self._background_registry
        if registry is None:
            # No registry — create a minimal one for this session.
            from cli.workbench_app.background_panel import BackgroundTaskRegistry
            self._background_registry = BackgroundTaskRegistry()
            registry = self._background_registry

        task = registry.register(
            description=command.strip(),
            owner="user",
        )
        self._store.set_state(append_message(
            "meta", f"Background task {task.task_id} started: {command.strip()}",
        ))

        def _run() -> None:
            from cli.workbench_app.background_panel import TaskStatus

            registry.update(task.task_id, status=TaskStatus.RUNNING)
            try:
                self._run_orchestrator_turn(command.strip())
                registry.update(
                    task.task_id,
                    status=TaskStatus.COMPLETED,
                    detail="done",
                )
            except Exception as exc:
                logger.warning("Background task %s failed", task.task_id, exc_info=True)
                registry.update(
                    task.task_id,
                    status=TaskStatus.FAILED,
                    detail=str(exc)[:200],
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    # ------------------------------------------------------------------ dispatch

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
            self._store.set_state(append_message("user", raw.strip()))
            self._run_shell_command(route.payload)
            return route

        if route.kind == InputKind.BACKGROUND:
            self._store.set_state(append_message("user", raw.strip()))
            self._run_background_command(route.payload)
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
            self._store.set_state(append_message("user", raw.strip()))
            if self._orchestrator is not None:
                # Run the LLM turn in a background thread so we don't
                # block the Textual event loop.
                thread = threading.Thread(
                    target=self._run_orchestrator_turn,
                    args=(raw.strip(),),
                    daemon=True,
                )
                thread.start()
            else:
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
