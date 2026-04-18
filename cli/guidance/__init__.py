"""Proactive guidance for the AgentLab workbench.

Surfaces context-aware next-step suggestions grounded in real workspace,
session, eval, and provider state. Inspired by Claude Code's ``tipScheduler``
and ``promptSuggestion`` services but narrowed to AgentLab's operator flows
(eval → optimize → review → deploy).

The public surface is intentionally small:

- :class:`Suggestion` — one grounded recommendation.
- :class:`GuidanceContext` — the duck-typed state a rule is allowed to read.
- :func:`evaluate_rules` — runs every registered rule against a context and
  returns a priority-sorted, dedup'd list of suggestions.
- :class:`SuggestionHistory` — tracks dismissal + cooldown so the same
  recommendation doesn't fire on every keystroke.
"""

from cli.guidance.types import (
    GuidanceContext,
    Suggestion,
    SuggestionRule,
)
from cli.guidance.engine import (
    DEFAULT_RULES,
    SuggestionHistory,
    evaluate_rules,
    select_suggestions,
)
from cli.guidance.context_builder import (
    build_context_from_workspace,
    history_path_for_workspace,
)

__all__ = [
    "DEFAULT_RULES",
    "GuidanceContext",
    "Suggestion",
    "SuggestionHistory",
    "SuggestionRule",
    "build_context_from_workspace",
    "evaluate_rules",
    "history_path_for_workspace",
    "select_suggestions",
]
