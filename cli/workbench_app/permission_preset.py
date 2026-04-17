"""Apply AgentLab risk-aware permission defaults to a ``PermissionManager``.

The Claude-Code-style default mode (see
:data:`cli.permissions._MODE_RULES["default"]`) routes any tool not in its
small ``ask`` list (``FileEdit``/``FileWrite``/``Bash``/``ConfigEdit``) to
``allow`` via the ``allow: ["*"]`` catch-all. Out of the box that lets the
model run ``EvalRun``, ``Deploy:*``, ``ImproveRun`` and ``ImproveAccept``
without prompting — each of which costs tokens and/or mutates production.

This preset closes that gap by adding session-ask patterns via the
in-memory :meth:`cli.permissions.PermissionManager.ask_for_session` hook.
Decision precedence keeps workspace explicit rules on top: a user who
allowlists ``tool:EvalRun`` in ``.agentlab/settings.json`` still gets
``allow``; everyone else gets ``ask``.

Read-only inspection tools (``ImproveList``/``ImproveShow``/``ImproveDiff``)
carry ``read_only=True`` on the ``Tool`` subclass, so
:meth:`cli.permissions.PermissionManager.decision_for_tool` short-circuits
them to ``allow`` before reaching this layer — no need to include them here.
"""

from __future__ import annotations

from cli.permissions import PermissionManager


AGENTLAB_ASK_PATTERNS: list[str] = [
    "tool:EvalRun",
    "tool:ImproveRun",
    "tool:ImproveAccept",
    "tool:Deploy:*",
]
"""Tool-action patterns that should always prompt the user.

* ``tool:EvalRun`` — runs a live eval; costs LLM tokens and writes rows to
  the eval-run store.
* ``tool:ImproveRun`` — runs eval → optimize; costs tokens and writes
  attempt rows to optimization memory.
* ``tool:ImproveAccept`` — deploys an accepted improvement (mutates the
  active production config).
* ``tool:Deploy:*`` — matches every Deploy strategy
  (``canary``/``immediate``/``full``/…); mutates production state.
"""


def apply_agentlab_defaults(manager: PermissionManager) -> None:
    """Install AgentLab-aware permission rules on ``manager``.

    Purely in-memory — never mutates ``.agentlab/settings.json``. Safe to
    call multiple times: ``ask_for_session`` is idempotent per pattern.

    Decision precedence after this call (highest to lowest):

    1. ``_session_deny``, ``_session_allow`` — user dialog choices win.
    2. Workspace ``settings.json::permissions.rules`` — explicit config wins.
    3. These preset patterns — force ``ask`` for every listed action.
    4. Mode defaults from :data:`cli.permissions._MODE_RULES`.
    """
    for pattern in AGENTLAB_ASK_PATTERNS:
        manager.ask_for_session(pattern)


__all__ = ["AGENTLAB_ASK_PATTERNS", "apply_agentlab_defaults"]
