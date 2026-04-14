"""Specialist definitions for the Builder multi-agent workflow."""

from __future__ import annotations

from dataclasses import dataclass

from builder.types import SpecialistRole


@dataclass(frozen=True)
class SpecialistDefinition:
    """Specification for one builder specialist subagent."""

    role: SpecialistRole
    display_name: str
    description: str
    tools: list[str]
    permission_scope: list[str]
    context_template: str


SPECIALISTS: dict[SpecialistRole, SpecialistDefinition] = {
    SpecialistRole.ORCHESTRATOR: SpecialistDefinition(
        role=SpecialistRole.ORCHESTRATOR,
        display_name="Orchestrator",
        description=(
            "Coordinates specialist handoffs, validates plans, and keeps artifacts aligned "
            "to user intent."
        ),
        tools=["route", "handoff", "task_planner", "session_memory"],
        permission_scope=["read"],
        context_template=(
            "Session: {session_id}\n"
            "Task: {task_id}\n"
            "Goal: coordinate specialists and keep changes reviewable."
        ),
    ),
    SpecialistRole.BUILD_ENGINEER: SpecialistDefinition(
        role=SpecialistRole.BUILD_ENGINEER,
        display_name="Build Engineer",
        description="Implements agent configuration, source, scaffold, and integration changes.",
        tools=["code_search", "code_edit", "artifact_builder", "test_runner"],
        permission_scope=["read", "source_write"],
        context_template=(
            "Implement the planned builder change, preserve existing flows, and attach tests."
        ),
    ),
    SpecialistRole.REQUIREMENTS_ANALYST: SpecialistDefinition(
        role=SpecialistRole.REQUIREMENTS_ANALYST,
        display_name="Requirements Analyst",
        description="Converts ambiguous requests into concrete goals, assumptions, and risks.",
        tools=["requirements_parser", "memory_reader", "constraints_extractor"],
        permission_scope=["read"],
        context_template=(
            "Read project instructions, summarize requirements, and produce acceptance criteria."
        ),
    ),
    SpecialistRole.PROMPT_ENGINEER: SpecialistDefinition(
        role=SpecialistRole.PROMPT_ENGINEER,
        display_name="Prompt Engineer",
        description="Improves prompts, XML instructions, examples, and response policies.",
        tools=["instruction_editor", "prompt_linter", "xml_instruction_tools", "example_curator"],
        permission_scope=["read", "source_write"],
        context_template=(
            "Revise prompts and instructions with targeted diffs and regression evidence."
        ),
    ),
    SpecialistRole.ADK_ARCHITECT: SpecialistDefinition(
        role=SpecialistRole.ADK_ARCHITECT,
        display_name="ADK Architect",
        description="Designs agent graph topology and ADK wiring changes.",
        tools=["adk_graph_reader", "adk_graph_diff", "topology_validator"],
        permission_scope=["read"],
        context_template=(
            "Propose ADK graph changes with before/after structure and rationale."
        ),
    ),
    SpecialistRole.TOOL_ENGINEER: SpecialistDefinition(
        role=SpecialistRole.TOOL_ENGINEER,
        display_name="Tool/Integration Engineer",
        description="Implements tools, adapters, and integration contracts.",
        tools=["code_search", "code_edit", "integration_tester"],
        permission_scope=["read", "source_write", "external_network"],
        context_template="Implement and validate tool integrations with safe defaults.",
    ),
    SpecialistRole.SKILL_AUTHOR: SpecialistDefinition(
        role=SpecialistRole.SKILL_AUTHOR,
        display_name="Skill Author",
        description="Creates and updates buildtime/runtime skills and manifests.",
        tools=["skill_registry", "manifest_editor", "skill_linter"],
        permission_scope=["read", "source_write"],
        context_template="Author skill content, manifest metadata, and provenance notes.",
    ),
    SpecialistRole.GUARDRAIL_AUTHOR: SpecialistDefinition(
        role=SpecialistRole.GUARDRAIL_AUTHOR,
        display_name="Guardrail Author",
        description="Designs and attaches policy guardrails with scoped inheritance.",
        tools=["guardrail_editor", "policy_tester", "safety_analyzer"],
        permission_scope=["read", "source_write"],
        context_template="Attach or revise guardrails and capture failure examples.",
    ),
    SpecialistRole.EVAL_AUTHOR: SpecialistDefinition(
        role=SpecialistRole.EVAL_AUTHOR,
        display_name="Eval Author",
        description="Creates eval slices and validates outcomes before apply/release.",
        tools=["eval_generator", "eval_runner", "quality_scorer"],
        permission_scope=["read", "source_write"],
        context_template="Generate eval bundles and summarize before/after quality deltas.",
    ),
    SpecialistRole.EVAL_RUNNER: SpecialistDefinition(
        role=SpecialistRole.EVAL_RUNNER,
        display_name="Eval Runner",
        description="Executes the eval suite against the active agent config and returns scores.",
        tools=["eval_runner", "results_store"],
        permission_scope=["read"],
        context_template=(
            "Run the eval harness deterministically and return composite scores, "
            "per-case outcomes, and failure fingerprints for downstream analysis."
        ),
    ),
    SpecialistRole.LOSS_ANALYST: SpecialistDefinition(
        role=SpecialistRole.LOSS_ANALYST,
        display_name="Loss Analyst",
        description="Clusters eval failures and narrates the dominant loss patterns.",
        tools=["trace_search", "failure_clusterer", "summary_writer"],
        permission_scope=["read"],
        context_template=(
            "Read eval_runner output, cluster failing cases by root cause, and produce "
            "a narrative loss analysis with targeted hypotheses the optimizer can act on."
        ),
    ),
    SpecialistRole.OPTIMIZATION_ENGINEER: SpecialistDefinition(
        role=SpecialistRole.OPTIMIZATION_ENGINEER,
        display_name="Optimization Engineer",
        description="Turns eval evidence into targeted optimizer experiments and reviewable changes.",
        tools=["optimizer", "skill_engine", "experiment_runner", "change_card_writer"],
        permission_scope=["read", "source_write", "benchmark_spend"],
        context_template=(
            "Use eval evidence and build-time skills to propose measured optimization changes."
        ),
    ),
    SpecialistRole.INSTRUCTION_OPTIMIZER: SpecialistDefinition(
        role=SpecialistRole.INSTRUCTION_OPTIMIZER,
        display_name="Instruction Optimizer",
        description="Proposes axis-scoped prompt / instruction edits grounded in loss analysis.",
        tools=["instruction_editor", "prompt_linter", "change_card_writer"],
        permission_scope=["read", "source_write"],
        context_template=(
            "Read the loss analyst output and emit a single instructions axis change card "
            "with hypothesis, targeted diff, expected delta, and verification plan."
        ),
    ),
    SpecialistRole.GUARDRAIL_OPTIMIZER: SpecialistDefinition(
        role=SpecialistRole.GUARDRAIL_OPTIMIZER,
        display_name="Guardrail Optimizer",
        description="Proposes axis-scoped guardrail policy updates grounded in loss analysis.",
        tools=["guardrail_editor", "policy_tester", "change_card_writer"],
        permission_scope=["read", "source_write"],
        context_template=(
            "Read the loss analyst output and emit a single guardrails axis change card "
            "with policy deltas, failing example, expected delta, and verification plan."
        ),
    ),
    SpecialistRole.CALLBACK_OPTIMIZER: SpecialistDefinition(
        role=SpecialistRole.CALLBACK_OPTIMIZER,
        display_name="Callback Optimizer",
        description="Proposes axis-scoped callback / tool-routing changes grounded in loss analysis.",
        tools=["code_edit", "integration_tester", "change_card_writer"],
        permission_scope=["read", "source_write"],
        context_template=(
            "Read the loss analyst output and emit a single callbacks axis change card "
            "with targeted callback edits, expected delta, and verification plan."
        ),
    ),
    SpecialistRole.TRACE_ANALYST: SpecialistDefinition(
        role=SpecialistRole.TRACE_ANALYST,
        display_name="Trace Analyst",
        description="Investigates traces, bookmarks evidence, and proposes fixes.",
        tools=["trace_search", "span_timeline", "blame_mapper"],
        permission_scope=["read"],
        context_template="Analyze traces, isolate root causes, and attach evidence chains.",
    ),
    SpecialistRole.DEPLOYMENT_ENGINEER: SpecialistDefinition(
        role=SpecialistRole.DEPLOYMENT_ENGINEER,
        display_name="Deployment Engineer",
        description="Plans deploy, canary, rollback, and environment readiness work.",
        tools=["deploy_planner", "canary_checker", "rollback_planner", "release_health_check"],
        permission_scope=["read", "deployment"],
        context_template=(
            "Prepare deployment steps with canary evidence, rollback plan, and release gates."
        ),
    ),
    SpecialistRole.RELEASE_MANAGER: SpecialistDefinition(
        role=SpecialistRole.RELEASE_MANAGER,
        display_name="Release Manager",
        description="Packages release candidates and manages deploy/rollback flow.",
        tools=["release_packager", "deploy_executor", "rollback_planner"],
        permission_scope=["read", "deployment"],
        context_template="Verify release readiness from artifacts, eval bundles, and approvals.",
    ),
}


_INTENT_KEYWORDS: dict[SpecialistRole, tuple[str, ...]] = {
    SpecialistRole.BUILD_ENGINEER: (
        "build",
        "implement",
        "implementation",
        "scaffold",
        "code",
        "create agent",
    ),
    SpecialistRole.REQUIREMENTS_ANALYST: (
        "requirements",
        "spec",
        "scope",
        "clarify",
        "assumption",
    ),
    SpecialistRole.PROMPT_ENGINEER: (
        "prompt",
        "instruction",
        "instructions",
        "system prompt",
        "examples",
        "few-shot",
    ),
    SpecialistRole.ADK_ARCHITECT: ("adk", "graph", "topology", "architecture"),
    SpecialistRole.TOOL_ENGINEER: ("tool", "integration", "api", "connector", "endpoint"),
    SpecialistRole.SKILL_AUTHOR: ("skill", "runtime skill", "buildtime skill", "manifest"),
    SpecialistRole.GUARDRAIL_AUTHOR: ("guardrail", "policy", "safety", "pii"),
    SpecialistRole.EVAL_AUTHOR: ("eval", "benchmark", "quality", "regression", "test"),
    SpecialistRole.EVAL_RUNNER: ("eval run", "run eval", "execute eval", "benchmark run"),
    SpecialistRole.LOSS_ANALYST: (
        "loss pattern",
        "failure cluster",
        "failure analysis",
        "loss analysis",
        "regression analysis",
    ),
    SpecialistRole.OPTIMIZATION_ENGINEER: (
        "optimize",
        "optimization",
        "improve",
        "improvement",
        "failure",
        "experiment",
    ),
    SpecialistRole.INSTRUCTION_OPTIMIZER: (
        "instruction optimizer",
        "prompt optimization",
        "tune prompt",
        "refine instructions",
    ),
    SpecialistRole.GUARDRAIL_OPTIMIZER: (
        "guardrail optimizer",
        "tune guardrail",
        "policy tuning",
        "refine guardrail",
    ),
    SpecialistRole.CALLBACK_OPTIMIZER: (
        "callback optimizer",
        "tune callback",
        "tool routing",
        "refine callback",
    ),
    SpecialistRole.TRACE_ANALYST: ("trace", "span", "failure", "why", "blame"),
    SpecialistRole.DEPLOYMENT_ENGINEER: (
        "deploy",
        "deployment",
        "canary",
        "rollback",
        "environment",
        "ship",
    ),
    SpecialistRole.RELEASE_MANAGER: ("release", "deploy", "rollback", "promote"),
}


def get_specialist(role: SpecialistRole) -> SpecialistDefinition:
    """Return specialist definition by role."""

    return SPECIALISTS[role]


def list_specialists() -> list[SpecialistDefinition]:
    """Return all specialist definitions in deterministic role order."""

    return [SPECIALISTS[role] for role in SpecialistRole]


def get_specialist_keywords(role: SpecialistRole) -> tuple[str, ...]:
    """Return intent keywords registered for a specialist role."""

    return _INTENT_KEYWORDS.get(role, ())


def detect_specialist_by_intent(message: str) -> SpecialistRole:
    """Select the specialist that best matches the provided message."""

    text = message.lower()
    best_role = SpecialistRole.ORCHESTRATOR
    best_score = 0
    for role, keywords in _INTENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_role = role
            best_score = score
    return best_role
