"""Coordinator worker for ``/skills gap`` and ``/skills generate <slug>``.

The worker's job depends on the ``skills.subcommand`` that the ``/skills``
slash handler placed in the coordinator context:

- ``gap`` — emit a prioritised ``skill_gap_report`` artifact. The default
  implementation reads any persisted :class:`agent_skills.types.SkillGap`
  records from the :class:`AgentSkillStore` so the operator sees the
  existing gap backlog ordered by impact_score × frequency.
- ``generate`` — emit a ``generated_skill`` artifact (code + manifest) for
  the requested slug and persist it through the store via
  :meth:`AgentSkillStore.save_from_coordinator_artifact`.

The worker deliberately never calls an LLM — the LLM path owns prompt
content through :mod:`builder.worker_prompts`, and this adapter produces
deterministic, inspectable output suitable for CI and for the test suite.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from agent_skills.store import AgentSkillStore
from agent_skills.types import GeneratedFile, GeneratedSkill
from builder.types import WorkerExecutionResult
from builder.worker_adapters import WorkerAdapter, WorkerAdapterContext


@dataclass
class SkillAuthorWorker:
    """Coordinator worker that backs ``/skills gap`` and ``/skills generate``.

    ``store_factory`` lets tests bind the worker to a custom database path
    without patching global state. Production callers leave it unset and
    get the default ``.agentlab/agent_skills.db`` location.
    """

    store_factory: Any = None
    name: str = "skill_author_worker"

    def execute(self, context: WorkerAdapterContext) -> WorkerExecutionResult:
        skills_meta = self._skills_meta(context)
        subcommand = str(skills_meta.get("subcommand") or "gap").lower()
        if subcommand == "generate":
            return self._generate(context, skills_meta)
        return self._gap(context, skills_meta)

    # ------------------------------------------------------------------ gap

    def _gap(
        self,
        context: WorkerAdapterContext,
        skills_meta: dict[str, Any],
    ) -> WorkerExecutionResult:
        store = self._store()
        existing_gaps = store.list_gaps() if store is not None else []
        ranked = sorted(
            existing_gaps,
            key=lambda g: float(g.get("impact_score", 0)) * float(g.get("frequency", 1)),
            reverse=True,
        )
        if not ranked:
            ranked = [_default_gap_proposal(context, skills_meta)]

        gap_payload = {
            "goal": context.run.goal,
            "gaps": ranked,
            "total_gaps": len(ranked),
            "notes": skills_meta.get("notes", ""),
        }
        report = {
            "skill_gap_report": gap_payload,
            "skill_manifest": {
                "mode": "gap",
                "summary": f"{len(ranked)} gap(s) ranked by impact × frequency.",
                "highest_gap_id": ranked[0].get("gap_id") if ranked else None,
            },
            "skill_validation": {
                "status": "not_applicable",
                "reason": "Gap turns do not emit skills; validation skipped.",
            },
        }
        summary = (
            f"Surfaced {len(ranked)} skill gap"
            f"{'' if len(ranked) == 1 else 's'} ordered by impact × frequency."
        )
        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=summary,
            artifacts=report,
            context_used={
                "context_boundary": context.context["context_boundary"],
                "skills_subcommand": "gap",
            },
            output_payload={
                "adapter": self.name,
                "subcommand": "gap",
                "review_required": True,
                "next_actions": [
                    "Pick a gap and run /skills generate <slug> to author a skill.",
                ],
            },
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": context.state.node_id,
                "adapter": self.name,
            },
        )

    # -------------------------------------------------------------- generate

    def _generate(
        self,
        context: WorkerAdapterContext,
        skills_meta: dict[str, Any],
    ) -> WorkerExecutionResult:
        slug = str(skills_meta.get("slug") or "").strip() or "untitled_skill"
        notes = str(skills_meta.get("notes") or "").strip()
        manifest, code, files = _skill_scaffold(slug, notes)
        gap_id = str(skills_meta.get("gap_id") or f"gap-{slug}")
        generated = GeneratedSkill(
            skill_id=f"skill-{uuid.uuid4()}",
            gap_id=gap_id,
            platform=str(skills_meta.get("platform") or "adk"),
            skill_type=str(skills_meta.get("skill_type") or "tool"),
            name=slug,
            description=notes
            or f"Auto-generated skill scaffold for {slug}.",
            source_code=code,
            config_yaml=manifest,
            files=files,
            eval_criteria=[
                {
                    "name": f"{slug}_smoke",
                    "description": "Smoke check that the skill is invocable.",
                }
            ],
            estimated_improvement=0.1,
            confidence="low",
            status="draft",
            review_notes=(
                "Scaffold produced by SkillAuthorWorker; review code and "
                "manifest before approving."
            ),
            created_at=time.time(),
        )
        save_record: dict[str, Any] = {
            "skill_id": generated.skill_id,
            "saved": False,
            "reason": "no_store",
        }
        store = self._store()
        if store is not None:
            store.save_from_coordinator_artifact(generated.to_dict())
            save_record = {"skill_id": generated.skill_id, "saved": True}

        summary = f"Generated skill scaffold for '{slug}' and persisted the manifest."
        return WorkerExecutionResult(
            node_id=context.state.node_id,
            worker_role=context.state.worker_role,
            summary=summary,
            artifacts={
                "generated_skill": generated.to_dict(),
                "skill_manifest": {
                    "slug": slug,
                    "platform": generated.platform,
                    "skill_type": generated.skill_type,
                    "manifest": manifest,
                    "save_record": save_record,
                },
                "skill_validation": {
                    "status": "draft",
                    "checks": ["manifest_yaml_non_empty", "source_code_non_empty"],
                    "manifest_yaml_non_empty": bool(manifest.strip()),
                    "source_code_non_empty": bool(code.strip()),
                },
            },
            context_used={
                "context_boundary": context.context["context_boundary"],
                "skills_subcommand": "generate",
                "slug": slug,
            },
            output_payload={
                "adapter": self.name,
                "subcommand": "generate",
                "slug": slug,
                "review_required": True,
                "next_actions": [
                    f"Review the generated scaffold for '{slug}' and approve via "
                    "/skills list before wiring it into the agent.",
                ],
            },
            provenance={
                "run_id": context.run.run_id,
                "plan_id": context.run.plan_id,
                "node_id": context.state.node_id,
                "adapter": self.name,
                "slug": slug,
            },
        )

    # --------------------------------------------------------------- helpers

    def _skills_meta(self, context: WorkerAdapterContext) -> dict[str, Any]:
        value = context.context.get("skills")
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _store(self) -> AgentSkillStore | None:
        if self.store_factory is None:
            try:
                return AgentSkillStore()
            except Exception:
                return None
        try:
            return self.store_factory()
        except Exception:
            return None


def _default_gap_proposal(
    context: WorkerAdapterContext,
    skills_meta: dict[str, Any],
) -> dict[str, Any]:
    """Fall back to a synthesized gap when the store has none."""
    goal = context.run.goal or "support agent"
    notes = skills_meta.get("notes", "")
    return {
        "gap_id": f"synth-{uuid.uuid4()}",
        "gap_type": "missing_tool",
        "description": f"Synthesized gap proposal for: {goal}",
        "failure_family": "tool_error",
        "frequency": 1,
        "impact_score": 0.5,
        "suggested_name": "tool_scaffold",
        "suggested_platform": "adk",
        "evidence": [],
        "context": {"notes": notes},
    }


def _skill_scaffold(slug: str, notes: str) -> tuple[str, str, list[GeneratedFile]]:
    """Return (manifest_yaml, source_code, files) for a generate scaffold."""
    manifest = (
        "skills:\n"
        f"  - id: {slug}\n"
        f"    name: {slug}\n"
        "    kind: runtime\n"
        "    version: '1.0.0'\n"
        f"    description: 'Auto-generated skill scaffold for {slug}.'\n"
        "    domain: general\n"
        "    tags:\n"
        "      - generated\n"
    )
    code = (
        f"\"\"\"Auto-generated skill scaffold for {slug}.\"\"\"\n\n"
        f"def {slug}(*args, **kwargs):\n"
        "    \"\"\"Replace this stub with real behavior.\"\"\"\n"
        f"    return {{'slug': '{slug}', 'notes': {notes!r}}}\n"
    )
    files = [
        GeneratedFile(
            path=f"agent_skills/generated/{slug}.yaml",
            content=manifest,
            is_new=True,
        ),
        GeneratedFile(
            path=f"agent_skills/generated/{slug}.py",
            content=code,
            is_new=True,
        ),
    ]
    return manifest, code, files


__all__ = ["SkillAuthorWorker"]
