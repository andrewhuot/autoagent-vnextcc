"""Plan-mode approval gate for the Workbench coordinator.

When the permission mode is ``plan`` (cycled via Shift+Tab), the Workbench
must never execute workers without operator approval. :class:`PlanGate`
orchestrates that contract:

1. Call ``runtime.process_turn(..., dry_run=True)`` to build and persist a
   coordinator plan without running workers.
2. Render the plan (worker roster + next actions) for the operator.
3. Read a line from the operator and dispatch on the first token:
   - ``y`` / ``yes`` / ``approve`` → re-run ``process_turn`` for real.
   - ``n`` / ``no`` / ``abort`` → return the dry-run result as-is so the
     transcript still shows what would have happened.
   - ``edit ...`` / ``refine ...`` → append the remainder as an annotation
     to the original message and re-plan (at most :data:`MAX_EDIT_ROUNDS`
     times, to avoid an infinite edit loop).

The gate is intentionally provider-agnostic: the ``prompt_fn`` and
``echo_fn`` are injected so unit tests can drive it synchronously without
a real terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from builder.coordinator_turn import CoordinatorTurnResult


PromptFn = Callable[[str], str]
EchoFn = Callable[[str], None]


MAX_EDIT_ROUNDS = 5
"""Hard cap on ``edit`` redirections per gate invocation."""


@dataclass(frozen=True)
class PlanGateOutcome:
    """Result returned by :meth:`PlanGate.run`."""

    decision: str
    """One of ``"approved"``, ``"aborted"``, ``"edit_limit_reached"``."""
    result: CoordinatorTurnResult
    rounds: int
    """How many ``edit`` iterations the operator went through (0 if first y/n)."""


class PlanGate:
    """Wraps coordinator turns with a plan → approve → execute handshake."""

    def __init__(
        self,
        runtime: Any,
        *,
        prompt_fn: PromptFn,
        echo_fn: EchoFn,
        max_edit_rounds: int = MAX_EDIT_ROUNDS,
    ) -> None:
        self._runtime = runtime
        self._prompt = prompt_fn
        self._echo = echo_fn
        self._max_edit_rounds = max_edit_rounds

    def run(
        self,
        message: str,
        *,
        ctx: Any | None = None,
        command_intent: str | None = None,
    ) -> PlanGateOutcome:
        """Drive one operator turn through the plan-mode gate."""
        current_message = message
        rounds = 0
        while True:
            planned = self._runtime.process_turn(
                current_message,
                ctx=ctx,
                command_intent=command_intent,
                dry_run=True,
            )
            self._render(planned)
            decision_line = self._prompt("  plan> ").strip()
            decision, remainder = _parse_decision(decision_line)
            if decision == "approve":
                executed = self._runtime.process_turn(
                    current_message,
                    ctx=ctx,
                    command_intent=command_intent,
                )
                return PlanGateOutcome(
                    decision="approved",
                    result=executed,
                    rounds=rounds,
                )
            if decision == "abort":
                self._echo("  Plan aborted; no workers ran.")
                return PlanGateOutcome(
                    decision="aborted",
                    result=planned,
                    rounds=rounds,
                )
            # ``edit`` → append annotation and re-plan.
            if not remainder:
                self._echo(
                    "  Provide an edit note after `edit`, e.g. `edit add guardrail for PII`."
                )
                continue
            rounds += 1
            if rounds > self._max_edit_rounds:
                self._echo(
                    f"  Edit limit ({self._max_edit_rounds}) reached — returning last plan."
                )
                return PlanGateOutcome(
                    decision="edit_limit_reached",
                    result=planned,
                    rounds=rounds,
                )
            current_message = f"{current_message}\n\n[edit]: {remainder}"

    def _render(self, planned: CoordinatorTurnResult) -> None:
        """Echo the dry-run plan so the operator can approve or refine."""
        for line in planned.transcript_lines:
            self._echo(line)


def _parse_decision(line: str) -> tuple[str, str]:
    """Return a normalized decision + remainder from one operator line.

    Recognised verbs (case-insensitive): ``y``/``yes``/``approve`` → ``approve``;
    ``n``/``no``/``abort``/``cancel`` → ``abort``; ``edit``/``refine`` → ``edit``.
    Empty or unknown input falls through to ``edit`` with the raw text so the
    loop prompts the operator again with a hint.
    """
    if not line:
        return "edit", ""
    head, _, remainder = line.partition(" ")
    head_lower = head.lower()
    if head_lower in {"y", "yes", "approve", "ok"}:
        return "approve", ""
    if head_lower in {"n", "no", "abort", "cancel", "stop"}:
        return "abort", ""
    if head_lower in {"edit", "refine", "revise"}:
        return "edit", remainder.strip()
    # Treat bare text as an edit annotation — keep the whole line as remainder.
    return "edit", line.strip()


__all__ = [
    "MAX_EDIT_ROUNDS",
    "PlanGate",
    "PlanGateOutcome",
    "PromptFn",
    "EchoFn",
]
