"""Prompt composition for LLM-backed coordinator workers.

Each specialist role gets:

- A role-specific guidance fragment spliced into the system prompt.
- An artifact contract describing the exact JSON shape each artifact key
  must take. For V1 ``/build`` the contracts are schema-aware against
  :mod:`agent.config.schema` so a downstream synthesis step can map
  worker output into canonical IR patches without guessing field names.
- A shared envelope that teaches the model the JSON output contract.
- A user prompt assembled from the gathered worker context
  (dependency summaries, skill candidates, permission scope,
  expected artifacts, recommended tools).
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
        "surface open risks before any implementation worker runs. Keep each "
        "criterion testable and grounded in the goal text."
    ),
    SpecialistRole.BUILD_ENGINEER: (
        "Draft the concrete AgentConfig change as a reviewable candidate. "
        "Return a `config_draft` that is a partial AgentConfig dict with only "
        "the keys you want changed. Return a `source_diff` describing files "
        "you would touch (path + rationale) and `test_evidence` naming the "
        "smoke tests that would cover the change."
    ),
    SpecialistRole.PROMPT_ENGINEER: (
        "Revise or author system prompts keyed by role name "
        "(`root`, `support`, `orders`, or any custom specialist). Return a "
        "`prompt_diff` artifact keyed by prompt role with `before`/`after` "
        "strings, an `instruction_summary` in one line, and "
        "`prompt_regression_cases` listing short user prompts that should "
        "still succeed."
    ),
    SpecialistRole.ADK_ARCHITECT: (
        "Describe the agent graph topology change. Return an "
        "`agent_graph_diff` with `before` and `after` lists of "
        "{name, role, parent} nodes, and `topology_validation` listing "
        "invariants the new graph must preserve (cycles, orphans, "
        "handoff targets)."
    ),
    SpecialistRole.TOOL_ENGINEER: (
        "Propose tool adapters with AgentLab ToolConfig shape. Return a "
        "`tool_contract` keyed by tool name, each entry with `enabled`, "
        "`timeout_ms`, `description`, and optional `parameters` "
        "(list of {name, type, required}). Return `integration_test` with at "
        "least one scripted call that would exercise the happy path."
    ),
    SpecialistRole.SKILL_AUTHOR: (
        "Author or prioritise skills based on the context. When "
        "`skills.subcommand` is present the request comes from /skills:\n"
        "  - 'gap' → emit a skill_gap_report artifact (prioritised list of "
        "gaps with gap_type, impact_score, frequency, one-line rationale).\n"
        "  - 'generate <slug>' → emit a generated_skill artifact "
        "(YAML manifest + source code) plus a skill_manifest artifact with "
        "the manifest metadata.\n"
        "Otherwise (SKILL_AUTHOR as part of a /build roster) return a "
        "`skill_manifest` list of {slug, layer, rationale} and a "
        "`skill_validation` section describing the assertion each skill "
        "must satisfy before it is attached to the project. Always include "
        "rationale, expected impact, and a review note per candidate."
    ),
    SpecialistRole.GUARDRAIL_AUTHOR: (
        "Draft guardrail policies matching :class:`GuardrailConfig`. Return a "
        "`guardrail_policy` list of {name, type, enforcement, description} "
        "objects (type ∈ input|output|both, enforcement ∈ block|warn|log) and "
        "`safety_test_cases` listing adversarial inputs the guardrail must "
        "block. Explain why each guardrail is safe and reversible."
    ),
    SpecialistRole.EVAL_AUTHOR: (
        "Generate eval coverage tied to the goal. Return an `eval_bundle` "
        "with `name` and `cases` (each {prompt, expected_behavior}) and a "
        "`benchmark_plan` naming the smoke vs. regression tiers."
    ),
    SpecialistRole.OPTIMIZATION_ENGINEER: (
        "Translate eval evidence into axis-scoped change cards "
        "(instructions, guardrails, callbacks, tools). Each card must list "
        "the hypothesis, expected delta, and verification plan."
    ),
    SpecialistRole.EVAL_RUNNER: (
        "Execute the eval suite directly (no LLM). Return the composite "
        "scores envelope and the list of failure fingerprints as artifacts."
    ),
    SpecialistRole.LOSS_ANALYST: (
        "Read upstream eval runner output, cluster failing cases by root "
        "cause, and emit a narrative loss analysis with axis recommendations."
    ),
    SpecialistRole.INSTRUCTION_OPTIMIZER: (
        "Read the loss analyst output from dependency_summaries / upstream "
        "artifacts. Produce exactly one axis-scoped instructions change "
        "card: hypothesis, before/after instruction diff, expected delta, "
        "and verification plan. Do not touch guardrails or callbacks."
    ),
    SpecialistRole.GUARDRAIL_OPTIMIZER: (
        "Read the loss analyst output from dependency_summaries / upstream "
        "artifacts. Produce exactly one axis-scoped guardrails change card: "
        "policy delta, failing example, expected delta, and verification "
        "plan. Do not touch instructions or callbacks."
    ),
    SpecialistRole.CALLBACK_OPTIMIZER: (
        "Read the loss analyst output from dependency_summaries / upstream "
        "artifacts. Produce exactly one axis-scoped callbacks change card: "
        "targeted callback / tool-routing edits, expected delta, and "
        "verification plan. Do not touch instructions or guardrails."
    ),
    SpecialistRole.TRACE_ANALYST: (
        "Identify the failing spans, cluster similar failures, and propose a "
        "root-cause hypothesis. Return evidence chains, not fixes."
    ),
    SpecialistRole.DEPLOYMENT_ENGINEER: (
        "Prepare the canary plan, rollback steps, and health checks. Consume "
        "the gate_runner's regression_summary and gate_report from "
        "dependency_summaries — the rollout plan MUST cite the gate verdict "
        "and every failure reason must either be resolved or explicitly "
        "waived. Emit a deployment_plan artifact with rollout stages and a "
        "rollback_plan artifact with concrete revert commands."
    ),
    SpecialistRole.RELEASE_MANAGER: (
        "Package the release candidate and verify gate evidence. Read the "
        "gate_runner's regression_summary from dependency_summaries and do "
        "NOT recommend promotion when gate_passed is false. The promotion "
        "recommendation MUST list explicit approvals still required and the "
        "exact RELEASE_TRANSITIONS target status."
    ),
    SpecialistRole.GATE_RUNNER: (
        "Run the CI/CD gate against the candidate config. Return a "
        "gate_report artifact with gate_passed, regression_detected, "
        "failure_reasons, and candidate/baseline scores. A regression_summary "
        "artifact restates the verdict for downstream workers."
    ),
    SpecialistRole.PLATFORM_PUBLISHER: (
        "Write the release_candidate record for the target platform. Use the "
        "gate_report from dependency_summaries to decide which RELEASE_TRANSITIONS "
        "target status is allowed; when the gate fails, hold the candidate at "
        "'draft'. Emit release_candidate + publish_record artifacts with "
        "platform, status, and any transition_reason."
    ),
    SpecialistRole.ORCHESTRATOR: (
        "Synthesize the other workers' outputs into a coherent plan and "
        "call out blockers or missing evidence."
    ),
}


# Artifact contracts tell the model the exact JSON shape for each expected
# artifact key. Downstream ``apply_coordinator_synthesis`` in
# ``builder/workbench.py`` maps these shapes into canonical IR patches, so
# drift between the contract here and the IR mapper shows up as config
# validation errors at apply time.
_ROLE_ARTIFACT_CONTRACTS: dict[SpecialistRole, dict[str, dict[str, Any]]] = {
    SpecialistRole.REQUIREMENTS_ANALYST: {
        "acceptance_criteria": {
            "shape": "list[{id: str, criterion: str, verifiable_by: str}]",
            "notes": "Each criterion must be individually testable.",
        },
        "risk_notes": {
            "shape": "list[{risk: str, severity: 'low'|'medium'|'high', mitigation: str}]",
            "notes": "Include at least one risk; 'none' is not acceptable.",
        },
    },
    SpecialistRole.BUILD_ENGINEER: {
        "config_draft": {
            "shape": (
                "partial AgentConfig dict — keys from {prompts, tools_config, "
                "guardrails, handoffs, routing, model, generation}"
            ),
            "notes": (
                "Only include keys you are changing. Follow agent/config/schema.py "
                "field names exactly — 'prompts.root' string, 'guardrails' list, etc."
            ),
        },
        "source_diff": {
            "shape": "list[{path: str, change: 'add'|'modify'|'delete', rationale: str}]",
            "notes": "Describe files you would touch — do not include raw diff text.",
        },
        "test_evidence": {
            "shape": "list[{test_name: str, purpose: str}]",
            "notes": "Name smoke tests that prove the change works.",
        },
    },
    SpecialistRole.PROMPT_ENGINEER: {
        "prompt_diff": {
            "shape": "dict[str, {before: str, after: str}] keyed by prompt role",
            "notes": (
                "Roles are 'root', 'support', 'orders', 'recommendations', or a "
                "custom specialist name declared in routing.rules."
            ),
        },
        "instruction_summary": {
            "shape": "str (one sentence)",
            "notes": "Summarize the behavioral intent of the new prompt.",
        },
        "prompt_regression_cases": {
            "shape": "list[{input: str, should_still: str}]",
            "notes": "User prompts that must still succeed after the change.",
        },
    },
    SpecialistRole.ADK_ARCHITECT: {
        "agent_graph_diff": {
            "shape": (
                "{before: list[{name, role, parent}], "
                "after: list[{name, role, parent}]}"
            ),
            "notes": "Use null for root parents. Every node needs a unique name.",
        },
        "topology_validation": {
            "shape": "list[{invariant: str, holds: bool, reason: str}]",
            "notes": "Cover cycles, orphan nodes, and handoff target existence.",
        },
    },
    SpecialistRole.TOOL_ENGINEER: {
        "tool_contract": {
            "shape": (
                "dict[str, {enabled: bool, timeout_ms: int, description: str, "
                "parameters?: list[{name, type, required}]}]"
            ),
            "notes": "Key by tool name — these become tools_config entries.",
        },
        "integration_test": {
            "shape": "list[{tool: str, scenario: str, expected: str}]",
            "notes": "At least one happy-path scenario per new tool.",
        },
    },
    SpecialistRole.GUARDRAIL_AUTHOR: {
        "guardrail_policy": {
            "shape": (
                "list[{name: str, type: 'input'|'output'|'both', "
                "enforcement: 'block'|'warn'|'log', description: str}]"
            ),
            "notes": (
                "Maps directly to AgentConfig.guardrails. Keep descriptions under "
                "2 sentences and anchored to an observable failure mode."
            ),
        },
        "safety_test_cases": {
            "shape": "list[{input: str, guardrail: str, expected_action: str}]",
            "notes": "Adversarial inputs that the guardrail must catch.",
        },
    },
    SpecialistRole.EVAL_AUTHOR: {
        "eval_bundle": {
            "shape": (
                "{name: str, cases: list[{prompt: str, expected_behavior: str}]}"
            ),
            "notes": "Cases should be deterministic — no time-bound references.",
        },
        "benchmark_plan": {
            "shape": "{smoke: list[str], regression: list[str]}",
            "notes": "Lists name the case ids that belong in each tier.",
        },
    },
    SpecialistRole.SKILL_AUTHOR: {
        "skill_manifest": {
            "shape": (
                "list[{slug: str, layer: 'build'|'runtime'|'mixed', rationale: str}]"
            ),
            "notes": "Slugs must be kebab-case and unique in the project.",
        },
        "skill_validation": {
            "shape": "list[{slug: str, assertion: str}]",
            "notes": "Name the assertion that proves the skill is wired.",
        },
    },
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
- Artifact payloads MUST follow the contract shapes listed above.
- Keep each artifact payload under ~2kB; use terse structured data, not prose.
- "review_required" is true when the change would write source, touch
  guardrails, spend benchmark budget, or affect deployment.
- Never invent tools or permissions beyond the provided recommended_tools
  and permission_scope.
"""


def _format_artifact_contracts(role: SpecialistRole) -> str:
    """Return a human-readable contract block for the role's artifacts."""
    contracts = _ROLE_ARTIFACT_CONTRACTS.get(role)
    if not contracts:
        return ""
    lines = ["Artifact contracts (follow exactly):"]
    for name, spec in contracts.items():
        lines.append(f"- {name}: {spec['shape']}")
        notes = spec.get("notes")
        if notes:
            lines.append(f"    note: {notes}")
    return "\n".join(lines)


def build_worker_prompt(
    state: WorkerExecutionState,
    context: dict[str, Any],
    routed: dict[str, Any],
) -> WorkerPrompt:
    """Compose the system and user prompts handed to the LLM router."""

    role = state.worker_role
    specialist = get_specialist(role)
    guidance = _ROLE_GUIDANCE.get(role, "Execute the task and produce structured artifacts.")
    artifact_block = _format_artifact_contracts(role)

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
    ]
    if artifact_block:
        system_parts.extend([artifact_block, ""])
    system_parts.append(_OUTPUT_ENVELOPE)
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


def get_artifact_contract(role: SpecialistRole) -> dict[str, dict[str, Any]]:
    """Return a copy of the artifact contract for a role (or empty dict)."""
    return {name: dict(spec) for name, spec in _ROLE_ARTIFACT_CONTRACTS.get(role, {}).items()}


__all__ = [
    "WorkerPrompt",
    "build_worker_prompt",
    "get_artifact_contract",
]
