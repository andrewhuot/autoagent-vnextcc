"""Build-time skill registry for the coordinator-worker runtime.

The orchestrator uses this registry during ``plan_work`` to surface
build-time skill recommendations per worker node, and the runtime uses it
during ``_gather_context`` to inject rich descriptors into worker context.

This module is intentionally thin: it wraps :class:`core.skills.store.SkillStore`
filtered to ``SkillKind.BUILD`` and adds the goal-matching, context-shaping,
and invocation surfaces the coordinator needs without re-implementing
storage.

Two invocation paths are supported:

- **Python callable** — when ``Skill.metadata["python_callable"]`` resolves
  to a ``"module.fn"`` reference, the registry imports the function and calls
  it with ``(context)``. The return value is wrapped into a result dict.
- **Markdown playbook** — when no callable is set, the registry returns a
  descriptor that callers (typically :class:`SkillInvocationWorker`) can
  hand to an LLM router for execution. The descriptor includes the skill's
  ``instructions`` so prompt assembly stays in one place.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from core.skills.store import SkillStore
from core.skills.types import Skill, SkillKind


@dataclass(frozen=True)
class SkillInvocationResult:
    """Outcome of invoking a build-time skill via the registry."""

    skill_id: str
    skill_name: str
    mode: str  # "callable" | "playbook"
    summary: str
    artifacts: dict[str, Any]
    output_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return the API-safe representation of this invocation result."""
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "mode": self.mode,
            "summary": self.summary,
            "artifacts": dict(self.artifacts),
            "output_payload": dict(self.output_payload),
        }


class BuildtimeSkillRegistry:
    """Goal-aware lookup and invocation for build-time skills.

    The registry is read-mostly: callers (orchestrator + runtime) query it
    during planning and execution, but mutation flows back through the
    underlying :class:`SkillStore`. Pass an explicit store to share state
    with other AgentLab subsystems, or omit it to use the default
    ``.agentlab/skills.db`` location.
    """

    def __init__(self, store: SkillStore | None = None) -> None:
        self._store = store or SkillStore(db_path=".agentlab/skills.db")

    @property
    def store(self) -> SkillStore:
        """Return the underlying skill store (for callers that need raw access)."""
        return self._store

    def list(self, *, status: str | None = "active") -> list[Skill]:
        """Return all build-time skills, optionally filtered by status."""
        return self._store.list(kind=SkillKind.BUILD, status=status)

    def get(self, skill_id: str) -> Skill | None:
        """Return one build-time skill by id, or ``None`` if missing/runtime."""
        skill = self._store.get(skill_id)
        if skill is None or skill.kind != SkillKind.BUILD:
            return None
        return skill

    def match(self, goal: str, *, limit: int = 5) -> list[Skill]:
        """Return build-time skills relevant to ``goal``, ranked by overlap.

        Matching is keyword-based across name, description, capabilities,
        and tags. Effectiveness breaks ties so a previously-successful
        skill ranks above an unproven peer with the same overlap.
        """
        text = " ".join(str(goal or "").lower().split())
        if not text:
            return []
        tokens = {token for token in text.replace("_", " ").split() if token}
        if not tokens:
            return []

        scored: list[tuple[int, float, Skill]] = []
        for skill in self.list():
            haystack_parts: list[str] = [
                skill.name.lower().replace("_", " "),
                skill.description.lower(),
                " ".join(c.lower() for c in skill.capabilities),
                " ".join(t.lower() for t in skill.tags),
            ]
            haystack = " ".join(part for part in haystack_parts if part)
            overlap = sum(1 for token in tokens if token in haystack)
            if overlap == 0:
                continue
            effectiveness = (
                skill.effectiveness.success_rate * skill.effectiveness.avg_improvement
            )
            scored.append((overlap, effectiveness, skill))

        scored.sort(key=lambda triple: (triple[0], triple[1]), reverse=True)
        return [skill for _, _, skill in scored[:limit]]

    def describe(self, skill: Skill) -> dict[str, Any]:
        """Return a compact descriptor suitable for worker context injection."""
        return {
            "skill_id": skill.id,
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "capabilities": list(skill.capabilities),
            "tags": list(skill.tags),
            "domain": skill.domain,
            "invocation_mode": self._invocation_mode(skill),
        }

    def descriptors_for_goal(self, goal: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return ``describe`` payloads for the top matches of ``goal``."""
        return [self.describe(skill) for skill in self.match(goal, limit=limit)]

    def invoke(self, skill_id: str, context: dict[str, Any]) -> SkillInvocationResult:
        """Invoke a build-time skill, returning its structured outcome.

        Resolution order:

        1. ``Skill.metadata["python_callable"]`` — direct callable, treated
           as a deterministic mutation (no LLM required).
        2. Otherwise — return a playbook descriptor so the caller can route
           through an LLM. The result's ``output_payload["playbook"]``
           carries the instruction text needed for prompting.
        """
        skill = self.get(skill_id)
        if skill is None:
            raise ValueError(f"Build-time skill not found: {skill_id}")

        callable_ref = self._python_callable_ref(skill)
        if callable_ref:
            payload = self._invoke_callable(callable_ref, skill=skill, context=context)
            return SkillInvocationResult(
                skill_id=skill.id,
                skill_name=skill.name,
                mode="callable",
                summary=str(
                    payload.get("summary")
                    or f"Invoked build-time skill '{skill.name}' via {callable_ref}."
                ),
                artifacts=dict(payload.get("artifacts") or {}),
                output_payload={
                    "callable_ref": callable_ref,
                    "result": payload.get("result"),
                    "context_keys": sorted(context),
                },
            )

        return SkillInvocationResult(
            skill_id=skill.id,
            skill_name=skill.name,
            mode="playbook",
            summary=(
                f"Prepared playbook for build-time skill '{skill.name}'. "
                "Worker should execute the markdown instructions via the LLM."
            ),
            artifacts={"playbook": skill.instructions or skill.description},
            output_payload={
                "playbook_instructions": skill.instructions or skill.description,
                "capabilities": list(skill.capabilities),
                "context_keys": sorted(context),
            },
        )

    def _python_callable_ref(self, skill: Skill) -> str | None:
        """Return the ``module.fn`` reference for a skill, if declared."""
        meta = skill.metadata or {}
        ref = meta.get("python_callable") or meta.get("callable")
        if not isinstance(ref, str):
            return None
        ref = ref.strip()
        if ref.startswith("py:"):
            ref = ref[3:]
        if "." not in ref:
            return None
        return ref

    def _invoke_callable(
        self,
        callable_ref: str,
        *,
        skill: Skill,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve and call a ``module.fn`` reference."""
        module_path, _, attr_name = callable_ref.rpartition(".")
        if not module_path or not attr_name:
            raise ValueError(
                f"Invalid python_callable for skill '{skill.name}': {callable_ref!r}"
            )
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise ValueError(
                f"Cannot import skill callable module '{module_path}': {exc}"
            ) from exc
        target = getattr(module, attr_name, None)
        if target is None or not callable(target):
            raise ValueError(
                f"Skill callable '{callable_ref}' is not a callable attribute"
            )
        result = target(context)
        if isinstance(result, dict):
            return result
        return {"result": result, "summary": "", "artifacts": {}}

    def _invocation_mode(self, skill: Skill) -> str:
        """Classify how a skill will be invoked (``callable`` vs ``playbook``)."""
        return "callable" if self._python_callable_ref(skill) else "playbook"


__all__ = [
    "BuildtimeSkillRegistry",
    "SkillInvocationResult",
]
