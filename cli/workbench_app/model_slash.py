"""``/model`` slash command — list and switch the session-local active model.

T14 ports Claude Code's `/model` surface to the workbench. The command is a
:class:`~cli.workbench_app.commands.LocalCommand` (inline, no streaming
subprocess) with three modes:

* ``/model`` — list every model in ``agentlab.yaml`` with credential status,
  marking the session-active one with ``●``.
* ``/model <key>`` — set the session-local override. ``<key>`` may be a full
  ``provider:model`` key (e.g. ``anthropic:claude-opus-4-6``) or the bare
  model name (e.g. ``claude-opus-4-6``), case-insensitive.
* ``/model reset`` / ``/model clear`` — drop the override.

Session overrides live under ``session.settings_overrides["model"]`` so
:mod:`cli.sessions` persistence and ``/resume`` carry them forward. No
workspace-level settings are mutated — users who want a durable change
run ``agentlab model set`` via the Click surface.

The status bar already accepts a ``model_override`` parameter on
:func:`cli.workbench_app.status_bar.snapshot_from_workspace`; the workbench
app loop reads ``session.settings_overrides.get("model")`` and threads it in
after each refresh. Wiring that refresh into the app shell is a T16/T18
concern; T14 only owns the command surface and session mutation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Sequence

import click

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done

ModelLister = Callable[[str | Path], list[dict[str, Any]]]
"""Signature of :func:`cli.model.list_available_models` — injectable so tests
drive the handler without a real ``agentlab.yaml`` on disk."""


_RESET_TOKENS = frozenset({"reset", "clear", "none", "default", "unset"})


def _default_lister(root: str | Path) -> list[dict[str, Any]]:
    from cli.model import list_available_models

    return list_available_models(root)


def _resolve_root(workspace: Any | None) -> Path:
    if workspace is None:
        return Path(".")
    root = getattr(workspace, "root", None)
    if root is None:
        return Path(".")
    return Path(root)


def _session_override(session: Any | None) -> str | None:
    if session is None:
        return None
    overrides = getattr(session, "settings_overrides", None)
    if not isinstance(overrides, dict):
        return None
    value = overrides.get("model")
    return str(value) if value else None


def _match_model(
    available: Sequence[dict[str, Any]], raw: str
) -> dict[str, Any] | None:
    """Return the model dict whose key or bare model name matches ``raw``.

    Full ``provider:model`` keys win outright. Bare model names match only
    when a single entry carries that name — ambiguous short matches fall
    through so the user gets a clear "unknown model" error rather than a
    silently-wrong selection.
    """
    normalized = raw.strip().lower()
    if not normalized:
        return None
    for item in available:
        if str(item.get("key", "")).lower() == normalized:
            return item
    short = [
        item
        for item in available
        if str(item.get("model", "")).lower() == normalized
    ]
    if len(short) == 1:
        return short[0]
    return None


def _credential_note(item: dict[str, Any]) -> str:
    env = str(item.get("api_key_env") or "")
    if env and os.environ.get(env):
        return "key set"
    if env:
        return f"missing {env}"
    return "no credentials"


def _format_list(
    available: Sequence[dict[str, Any]], *, active_key: str | None
) -> str:
    """Render the multi-line model list for ``/model`` with no args."""
    lines: list[str] = [click.style("\n  Models", bold=True)]
    lowered_active = active_key.lower() if active_key else None
    for item in available:
        key = str(item.get("key", "?"))
        role = str(item.get("role", "?"))
        note = _credential_note(item)
        marker = "●" if lowered_active and key.lower() == lowered_active else "○"
        styled_marker = (
            click.style(marker, fg="green") if marker == "●" else marker
        )
        lines.append(f"    {styled_marker} {key}  role={role}  ({note})")
    lines.append("")
    return "\n".join(lines)


def _handle_model_with_lister(
    ctx: Any, lister: ModelLister, *args: str
) -> OnDoneResult:
    """Core handler — ``ctx`` typed as Any to avoid a slash↔model_slash cycle."""
    workspace = ctx.workspace
    root = _resolve_root(workspace)
    try:
        available = lister(root)
    except Exception as exc:  # Surface runtime/YAML errors as transcript text.
        return on_done(
            click.style(f"  Could not load models: {exc}", fg="red"),
            display="user",
        )

    if not available:
        return on_done(
            "  No models configured in agentlab.yaml.", display="user"
        )

    session = ctx.session
    active = _session_override(session)

    if not args:
        body = _format_list(available, active_key=active)
        meta: list[str] = []
        if active is not None:
            meta.append(f"Session override: {active}")
        else:
            meta.append("No session override — using workspace default.")
        return on_done(body, display="user", meta_messages=meta)

    token = args[0]
    if token.strip().lower() in _RESET_TOKENS:
        return _reset_override(ctx)
    return _set_override(ctx, available, token)


def _set_override(
    ctx: Any,
    available: Sequence[dict[str, Any]],
    raw: str,
) -> OnDoneResult:
    matched = _match_model(available, raw)
    if matched is None:
        return on_done(
            click.style(
                f"  Unknown model: {raw}. Run /model with no args for the list.",
                fg="red",
            ),
            display="user",
        )

    session = ctx.session
    if session is None:
        return on_done(
            click.style(
                "  No active session — cannot persist model override.",
                fg="yellow",
            ),
            display="user",
        )

    key = str(matched["key"])
    overrides = session.settings_overrides
    if not isinstance(overrides, dict):  # Defensive: freshly constructed sessions.
        overrides = {}
        session.settings_overrides = overrides
    overrides["model"] = key

    store = ctx.session_store
    persisted = False
    if store is not None:
        try:
            store.save(session)
            persisted = True
        except Exception as exc:
            return on_done(
                click.style(
                    f"  Set session model to {key} (not persisted: {exc}).",
                    fg="yellow",
                ),
                display="user",
                meta_messages=["Override applies for this run only."],
            )

    meta = ["Active for this session only — use /model reset to clear."]
    if not persisted:
        meta.append("Not persisted — no session store bound.")
    return on_done(
        click.style(f"  Session model → {key}", fg="green"),
        display="user",
        meta_messages=meta,
    )


def _reset_override(ctx: Any) -> OnDoneResult:
    session = ctx.session
    overrides = getattr(session, "settings_overrides", None) if session else None
    if not isinstance(overrides, dict) or "model" not in overrides:
        return on_done(
            "  No session model override to clear.", display="user"
        )
    previous = overrides.pop("model")
    store = ctx.session_store
    if store is not None:
        try:
            store.save(session)
        except Exception:
            # Best-effort persistence; the in-memory mutation already landed.
            pass
    return on_done(
        click.style(
            f"  Cleared session model override (was {previous}).", fg="green"
        ),
        display="user",
    )


def build_model_command(*, lister: ModelLister | None = None) -> LocalCommand:
    """Return the ``/model`` command. Inject ``lister`` in tests."""
    resolved = lister or _default_lister

    def _handler(ctx: Any, *args: str) -> OnDoneResult:
        return _handle_model_with_lister(ctx, resolved, *args)

    return LocalCommand(
        name="model",
        description="List or switch the active session model",
        handler=_handler,
        source="builtin",
        argument_hint="[provider/model | reset]",
        when_to_use="Use when a session needs a different model without editing config.",
    )


__all__ = ["ModelLister", "build_model_command"]
