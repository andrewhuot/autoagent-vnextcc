"""Scoped tool-allowlist overlay for an in-flight skill.

When the user invokes a skill, the model should see only the tools the
skill's frontmatter authorises. We implement that as an in-memory overlay
on :class:`PermissionManager` that denies any tool outside the skill's
``allowed_tools`` list, composes cleanly with plan-mode and mode rules,
and restores the prior state when the skill exits.

Usage::

    with scoped_allowlist(manager, allowed={"FileRead", "Grep"}):
        run_the_skill()

The context manager is re-entrant in the sense that nested scopes stack —
the inner scope intersects its allowlist with the outer one — so a skill
that invokes another skill never gains tools it wasn't authorised for.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def scoped_allowlist(
    manager,
    *,
    allowed: frozenset[str] | set[str] | tuple[str, ...],
) -> Iterator[None]:
    """Temporarily restrict the permission manager to ``allowed``.

    ``manager`` is any object with the session-override API introduced in
    Phase 1 (:class:`cli.permissions.PermissionManager`). We duck-type to
    avoid circular imports — the tests patch in a minimal fake."""
    if not hasattr(manager, "_session_allow") or not hasattr(manager, "_session_deny"):
        # The plan/exec layer didn't inject a manager with overlay support.
        # Run the skill without restriction rather than crashing — the
        # base mode rules still govern anything destructive.
        yield
        return

    allowed_set: frozenset[str] = frozenset(allowed)
    prior_deny_pattern = "__skill_overlay_deny__"

    # Compose with any outer overlay so nested skills inherit the
    # intersection rather than widening the surface.
    outer_overlay = getattr(manager, "_skill_allowlist", None)
    if isinstance(outer_overlay, frozenset):
        effective = outer_overlay & allowed_set
    else:
        effective = allowed_set
    setattr(manager, "_skill_allowlist", effective)

    # Inject a catch-all deny so decision_for_tool short-circuits for
    # non-whitelisted tools; the decision helper below lifts the deny by
    # consulting _skill_allowlist first.
    manager.deny_for_session(prior_deny_pattern)
    try:
        yield
    finally:
        # Drop the catch-all deny and restore the outer allowlist (or
        # remove the attribute entirely when we were the outermost scope).
        try:
            manager._session_deny.remove(prior_deny_pattern)
        except (ValueError, AttributeError):
            pass
        if isinstance(outer_overlay, frozenset):
            manager._skill_allowlist = outer_overlay
        else:
            try:
                delattr(manager, "_skill_allowlist")
            except AttributeError:
                pass


def skill_overlay_allows(manager, tool_name: str) -> bool | None:
    """Consult the overlay for ``tool_name``.

    Returns ``True`` when the tool is on the active skill allowlist,
    ``False`` when a skill is in flight but this tool isn't allowed, and
    ``None`` when no skill overlay is present. Callers (the permission
    manager) use the ``None`` to fall back to the normal decision chain.
    """
    overlay = getattr(manager, "_skill_allowlist", None)
    if not isinstance(overlay, frozenset):
        return None
    return tool_name in overlay


__all__ = ["scoped_allowlist", "skill_overlay_allows"]
