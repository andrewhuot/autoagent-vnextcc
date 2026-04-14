"""Prompt composition for LLM-backed coordinator workers.

Each specialist role gets:

- A role-specific guidance fragment spliced into the system prompt.
- A shared envelope that teaches the model the JSON output contract.
- A user prompt assembled from the gathered worker context
  (dependency summaries, skill candidates, permission scope,
  expected artifacts, recommended tools).

The prompt shapes are intentionally small here. Per-verb workstreams
(V1-V5) extend the role map with richer few-shot examples and
schema-constrained artifacts for BUILD_ENGINEER / PROMPT_ENGINEER /
GUARDRAIL_AUTHOR / EVAL_AUTHOR / OPTIMIZATION_ENGINEER / DEPLOYMENT_ENGINEER.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from builder.specialists import get_specialist
from builder.types import SpecialistRole, WorkerExecutionState


@dataclass(frozen=True)
class WorkerPrompt:
    """System + user prompt pair passed to the LLM router."""

    system: str
    user: str


_ROLE_GUIDANCE: dict[SpecialistRole, str] = {
    SpecialistRole.REQUIREMENTS_ANALYST: (
        "Restate the user goal as acceptance criteria, list assumptions, and "
        "surface open risks before any implementation worker runs."
    ),
    SpecialistRole.BUILD_ENGINEER: (
        "Draft the concrete agent configuration change as a reviewable "
        "candidate. Produce a config_candidate artifact with a short summary "
        "of what the diff contains and why it satisfies the goal."
    ),
    SpecialistRole.PROMPT_ENGINEER: (
        "Revise or author system prompts and instructions. Return targeted "
        "diffs (before/after) and a short rationale grounded in the goal."
    ),
    SpecialistRole.ADK_ARCHITECT: (
        "Describe the agent graph topology change with before/after nodes and "
        "the routing rationale. Flag any risk to existing specialists."
    ),
    SpecialistRole.TOOL_ENGINEER: (
        "Propose tool adapters, argument schemas, and integration contracts. "
        "Call out external permissions or secrets needed for review."
    ),
    SpecialistRole.SKILL_AUTHOR: (
        "Recommend build-time or runtime skills that would unblock the goal. "
        "For each candidate, include rationale, expected impact, and a short "
        "review note."
    ),
    SpecialistRole.GUARDRAIL_AUTHOR: (
        "Draft guardrail policies with enforcement level and a failing "
        "example. Explain why the guardrail is safe and reversible."
    ),
    SpecialistRole.EVAL_AUTHOR: (
        "Generate eval coverage suggestions tied to the goal. Name each "
        "suggested case and explain the behavior it verifies."
    ),
    SpecialistRole.OPTIMIZATION_ENGINEER: (
        "Translate eval evidence into axis-scoped change cards "
        "(instructions, guardrails, callbacks, tools). Each card must list "
        "the hypothesis, expected delta, and verification plan."
    ),
    SpecialistRole.TRACE_ANALYST: (
        "Identify the failing spans, cluster similar failures, and propose a "
        "root-cause hypothesis. Return evidence chains, not fixes."
    ),
    SpecialistRole.DEPLOYMENT_ENGINEER: (
        "Prepare the canary plan, rollback steps, and health checks. "
        "Call out required approvals explicitly."
    ),
    SpecialistRole.RELEASE_MANAGER: (
        "Package the release candidate, verify gate evidence, and state the "
        "promotion recommendation with explicit approvals still required."
    ),
    SpecialistRole.ORCHESTRATOR: (
        "Synthesize the other workers' outputs into a coherent plan and "
        "call out blockers or missing evidence."
    ),
}


_OUTPUT_ENVELOPE = """\
Return a single JSON object with this shape and no prose outside the JSON:

{
  "summary": "<one-sentence operator-facing summary>",
  "artifacts": {
    "<artifact_name>": { "...": "role-specific content" }
  },
  "output_payload": {
    "review_required": <bool>,
    "next_actions": [ "<short actionable line>" ],
    "notes": "<optional rationale>"
  }
}

Requirements:
- Each expected artifact name MUST appear as a key under "artifacts".
- Keep each artifact payload under ~2kB; use terse structured data, not prose.
- "review_required" is true when the change would write source, touch
  guardrails, spend benchmark budget, or affect deployment.
- Never invent tools or permissions beyond the provided recommended_tools
  and permission_scope.
"""


def build_worker_prompt(
    state: WorkerExecutionState,
    context: dict[str, Any],
    routed: dict[str, Any],
) -> WorkerPrompt:
    """Compose the system and user prompts handed to the LLM router."""

    role = state.worker_role
    specialist = get_specialist(role)
    guidance = _ROLE_GUIDANCE.get(role, "Execute the task and produce structured artifacts.")

    system_parts = [
        f"You are the {specialist.display_name} worker inside the AgentLab "
        "coordinator-worker harness.",
        specialist.description,
        f"Role guidance: {guidance}",
        "",
        specialist.context_template.format(
            session_id=context.get("session_id", "unknown"),
            task_id=context.get("task_id", "unknown"),
        )
        if "{session_id}" in specialist.context_template
        or "{task_id}" in specialist.context_template
        else specialist.context_template,
        "",
        _OUTPUT_ENVELOPE,
    ]
    system = "\n".join(part for part in system_parts if part is not None)

    user_payload = {
        "goal": context.get("goal", ""),
        "command_intent": context.get("command_intent"),
        "expected_artifacts": list(context.get("expected_artifacts", [])),
        "recommended_tools": list(routed.get("recommended_tools", [])),
        "permission_scope": list(routed.get("permission_scope", [])),
        "selected_tools": list(context.get("selected_tools", [])),
        "skill_candidates": list(context.get("skill_candidates", [])),
        "dependency_summaries": dict(context.get("dependency_summaries", {})),
        "context_boundary": context.get("context_boundary"),
        "routing_reason": routed.get("provenance", {}).get("routing_reason"),
    }
    user = json.dumps(user_payload, indent=2, sort_keys=True)
    return WorkerPrompt(system=system, user=user)


__all__ = [
    "WorkerPrompt",
    "build_worker_prompt",
]
