"""Context profile assembly and diagnostics for builder-facing workflows."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONTEXT_PROFILE = "balanced"


@dataclass(frozen=True)
class ContextProfile:
    """Named context strategy that controls what the agent receives and why."""

    name: str
    label: str
    description: str
    token_budget: int
    target_utilization: float
    include_project_memory: bool
    include_tool_catalog: bool
    include_examples: bool
    include_routing: bool
    include_recent_failures: bool
    include_retrieval_plan: bool
    compaction_trigger: float
    retention_ratio: float
    pro_mode: bool

    def with_overrides(
        self,
        *,
        token_budget: int | None = None,
        pro_mode: bool | None = None,
    ) -> ContextProfile:
        updates: dict[str, Any] = {}
        if token_budget is not None:
            updates["token_budget"] = token_budget
        if pro_mode is not None:
            updates["pro_mode"] = pro_mode
        return replace(self, **updates)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextComponent:
    """One traceable ingredient in the assembled model context."""

    component_id: str
    label: str
    kind: str
    source: str
    token_count: int
    budget_share: float
    priority: int
    included: bool
    notes: list[str]
    preview: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextDiagnostic:
    """Actionable lint finding for the context assembly strategy."""

    severity: str
    category: str
    message: str
    recommendation: str
    component_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextAssemblyPreview:
    """Full context-engineering preview shared by CLI, API, and UI."""

    profile_name: str
    profile_label: str
    status: str
    token_budget: int
    total_tokens: int
    utilization_ratio: float
    assembly_order: list[str]
    components: list[ContextComponent]
    diagnostics: list[ContextDiagnostic]
    pro_mode: bool
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "profile_label": self.profile_label,
            "status": self.status,
            "token_budget": self.token_budget,
            "total_tokens": self.total_tokens,
            "utilization_ratio": self.utilization_ratio,
            "assembly_order": self.assembly_order,
            "components": [component.to_dict() for component in self.components],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "pro_mode": self.pro_mode,
            "generated_at": self.generated_at,
        }


CONTEXT_PROFILE_PRESETS: dict[str, ContextProfile] = {
    "lean": ContextProfile(
        name="lean",
        label="Lean",
        description="Smallest useful context for fast iteration and narrow eval loops.",
        token_budget=8_000,
        target_utilization=0.55,
        include_project_memory=True,
        include_tool_catalog=False,
        include_examples=False,
        include_routing=True,
        include_recent_failures=False,
        include_retrieval_plan=True,
        compaction_trigger=0.65,
        retention_ratio=0.45,
        pro_mode=False,
    ),
    "balanced": ContextProfile(
        name="balanced",
        label="Balanced",
        description="Default profile for most builder and optimizer work.",
        token_budget=16_000,
        target_utilization=0.70,
        include_project_memory=True,
        include_tool_catalog=True,
        include_examples=True,
        include_routing=True,
        include_recent_failures=False,
        include_retrieval_plan=True,
        compaction_trigger=0.80,
        retention_ratio=0.60,
        pro_mode=True,
    ),
    "deep": ContextProfile(
        name="deep",
        label="Deep",
        description="High-recall profile for audits, migrations, and difficult failures.",
        token_budget=32_000,
        target_utilization=0.78,
        include_project_memory=True,
        include_tool_catalog=True,
        include_examples=True,
        include_routing=True,
        include_recent_failures=True,
        include_retrieval_plan=True,
        compaction_trigger=0.88,
        retention_ratio=0.72,
        pro_mode=True,
    ),
}


def estimate_tokens(text: str) -> int:
    """Estimate tokens cheaply so preview can run offline without model services."""
    cleaned = text.strip()
    if not cleaned:
        return 0
    char_estimate = math.ceil(len(cleaned) / 4)
    word_estimate = math.ceil(len(cleaned.split()) * 1.33)
    return max(1, char_estimate, word_estimate)


def context_profiles_payload() -> dict[str, Any]:
    """Return all selectable context profiles in stable product order."""
    return {
        "default_profile": DEFAULT_CONTEXT_PROFILE,
        "profiles": [profile.to_dict() for profile in CONTEXT_PROFILE_PRESETS.values()],
    }


def get_context_profile(
    name: str | None,
    *,
    token_budget: int | None = None,
    pro_mode: bool | None = None,
) -> ContextProfile:
    """Resolve a named profile and apply safe CLI/API overrides."""
    if token_budget is not None and token_budget <= 0:
        raise ValueError("Context token budget must be greater than zero.")
    normalized = (name or DEFAULT_CONTEXT_PROFILE).strip().lower()
    try:
        profile = CONTEXT_PROFILE_PRESETS[normalized]
    except KeyError as exc:
        allowed = ", ".join(CONTEXT_PROFILE_PRESETS)
        raise ValueError(f"Unknown context profile '{normalized}'. Choose one of: {allowed}.") from exc
    return profile.with_overrides(token_budget=token_budget, pro_mode=pro_mode)


def build_context_preview(
    agent_config: dict[str, Any] | None,
    *,
    profile: ContextProfile | None = None,
    project_memory_text: str = "",
    recent_failures: list[dict[str, Any]] | None = None,
) -> ContextAssemblyPreview:
    """Assemble and lint the context that would be sent for this agent config."""
    resolved_profile = profile or CONTEXT_PROFILE_PRESETS[DEFAULT_CONTEXT_PROFILE]
    config = agent_config or {}
    components = _build_components(
        config,
        profile=resolved_profile,
        project_memory_text=project_memory_text,
        recent_failures=recent_failures or [],
    )
    total_tokens = sum(component.token_count for component in components if component.included)
    utilization = total_tokens / resolved_profile.token_budget if resolved_profile.token_budget else 0.0
    components = [
        replace(
            component,
            budget_share=component.token_count / resolved_profile.token_budget
            if resolved_profile.token_budget
            else 0.0,
        )
        for component in components
    ]
    diagnostics = _diagnose_context(config, resolved_profile, components, total_tokens, project_memory_text)
    status = _status_from_diagnostics(diagnostics)
    assembly_order = [
        component.component_id
        for component in sorted(components, key=lambda item: item.priority)
        if component.included
    ]

    return ContextAssemblyPreview(
        profile_name=resolved_profile.name,
        profile_label=resolved_profile.label,
        status=status,
        token_budget=resolved_profile.token_budget,
        total_tokens=total_tokens,
        utilization_ratio=utilization,
        assembly_order=assembly_order,
        components=sorted(components, key=lambda item: item.priority),
        diagnostics=diagnostics,
        pro_mode=resolved_profile.pro_mode,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def build_context_preview_from_workspace(
    *,
    root: str | Path = ".",
    config_path: str | Path | None = None,
    profile_name: str | None = None,
    token_budget: int | None = None,
    pro_mode: bool | None = None,
    agent_config: dict[str, Any] | None = None,
    project_memory_text: str | None = None,
) -> ContextAssemblyPreview:
    """Load local workspace sources and build the same preview used by product surfaces."""
    profile = get_context_profile(profile_name, token_budget=token_budget, pro_mode=pro_mode)
    base = Path(root).resolve()
    config = agent_config if agent_config is not None else load_agent_config_for_preview(base, config_path)
    memory_text = project_memory_text if project_memory_text is not None else load_project_memory_for_preview(base)
    return build_context_preview(config, profile=profile, project_memory_text=memory_text)


def load_agent_config_for_preview(root: str | Path = ".", config_path: str | Path | None = None) -> dict[str, Any]:
    """Load a candidate agent config while keeping preview path reads inside the workspace."""
    base = Path(root).resolve()
    selected = _resolve_preview_config_path(base, config_path)
    if selected is None:
        return {}
    payload = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping in {selected}")
    return payload


def load_project_memory_for_preview(root: str | Path = ".") -> str:
    """Read layered project memory without creating new workspace directories."""
    base = Path(root).resolve()
    paths: list[Path] = [
        base / "AGENTLAB.md",
        base / "AGENTLAB.local.md",
    ]
    for dirname in (base / ".agentlab" / "rules", base / ".agentlab" / "memory"):
        if dirname.exists():
            paths.extend(sorted(dirname.glob("*.md")))

    sections: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        body = path.read_text(encoding="utf-8").strip()
        if body:
            sections.append(f"<!-- {path.name} -->\n{body}")
    return "\n\n".join(sections)


def _resolve_preview_config_path(base: Path, config_path: str | Path | None) -> Path | None:
    if config_path is not None:
        requested = Path(config_path)
        selected = requested if requested.is_absolute() else base / requested
        resolved = selected.resolve()
        if not _is_relative_to(resolved, base):
            raise ValueError(f"Config path must stay inside workspace: {config_path}")
        if not resolved.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return resolved

    candidates: list[Path] = []
    configs_dir = base / "configs"
    for name in ("active.yaml", "v001.yaml", "v001_base.yaml"):
        candidates.append(configs_dir / name)
    if configs_dir.exists():
        candidates.extend(sorted(configs_dir.glob("v*.yaml"), reverse=True))
    candidates.append(base / "agent" / "config" / "base_config.yaml")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _build_components(
    config: dict[str, Any],
    *,
    profile: ContextProfile,
    project_memory_text: str,
    recent_failures: list[dict[str, Any]],
) -> list[ContextComponent]:
    prompt_text = _format_prompts(config.get("prompts"))
    examples_text = _extract_examples(config)
    tools_text = _format_tools(config.get("tools"))
    routing_text = _format_yaml_like(config.get("routing"))
    strategy_text = _format_context_strategy(config, profile)
    retrieval_text = (
        "Use lightweight identifiers first. Load files, tool details, and retrieved documents "
        "just in time when the current task requires them."
    )
    failures_text = _format_recent_failures(recent_failures)

    raw_components = [
        ("instructions", "Instruction Hierarchy", "system_prompt", "agent_config.prompts", prompt_text, 10, True, [
            "Root and specialist instructions are loaded before optional context.",
            "Keep role, constraints, context, and examples visibly separated.",
        ]),
        ("project_memory", "Project Memory", "memory", "AGENTLAB.md + .agentlab/memory", project_memory_text, 20, profile.include_project_memory, [
            "Persistent builder knowledge should be concise and durable.",
        ]),
        ("context_strategy", "Context Strategy", "runtime_policy", "agent_config.context_* + selected profile", strategy_text, 30, True, [
            "Compaction, caching, and memory policy shape long-horizon behavior.",
        ]),
        ("retrieval_plan", "Retrieval Plan", "retrieval", "context profile", retrieval_text, 40, profile.include_retrieval_plan, [
            "Prefer references and targeted retrieval over preloading large corpora.",
        ]),
        ("tool_runtime", "Tool Runtime", "tool_catalog", "agent_config.tools", tools_text, 50, profile.include_tool_catalog, [
            "Tool names, descriptions, and response verbosity become agent context.",
        ]),
        ("routing", "Routing and Handoffs", "routing", "agent_config.routing", routing_text, 60, profile.include_routing, [
            "Routing rules and handoff expectations should stay compact and explicit.",
        ]),
        ("examples", "Few-Shot Examples", "examples", "agent_config.prompts/examples", examples_text, 70, profile.include_examples, [
            "Use diverse canonical examples; avoid repetitive pattern ruts.",
        ]),
        ("failure_evidence", "Recent Failure Evidence", "trace_evidence", "recent trace failures", failures_text, 80, profile.include_recent_failures, [
            "Useful wrong turns can help prevent repeated actions.",
        ]),
    ]

    components: list[ContextComponent] = []
    for component_id, label, kind, source, body, priority, included, notes in raw_components:
        preview = _compact_preview(body)
        components.append(
            ContextComponent(
                component_id=component_id,
                label=label,
                kind=kind,
                source=source,
                token_count=estimate_tokens(body) if included else 0,
                budget_share=0.0,
                priority=priority,
                included=bool(included),
                notes=list(notes),
                preview=preview,
            )
        )
    return components


def _diagnose_context(
    config: dict[str, Any],
    profile: ContextProfile,
    components: list[ContextComponent],
    total_tokens: int,
    project_memory_text: str,
) -> list[ContextDiagnostic]:
    diagnostics: list[ContextDiagnostic] = []
    utilization = total_tokens / profile.token_budget if profile.token_budget else 0.0

    if utilization > 1.0:
        diagnostics.append(
            ContextDiagnostic(
                severity="critical",
                category="budget",
                component_id=None,
                message=(
                    f"Context preview uses {total_tokens} estimated tokens, "
                    f"which exceeds the {profile.token_budget} token budget."
                ),
                recommendation="Use the lean profile, trim low-signal memory, or lower retrieved documents before eval.",
            )
        )
    elif utilization > profile.target_utilization:
        diagnostics.append(
            ContextDiagnostic(
                severity="warning",
                category="budget",
                component_id=None,
                message=(
                    f"Context preview uses {utilization:.0%} of the budget, above the "
                    f"{profile.target_utilization:.0%} target for {profile.name}."
                ),
                recommendation="Trim optional components or raise the budget only when eval evidence justifies it.",
            )
        )

    prompts = config.get("prompts") if isinstance(config.get("prompts"), dict) else {}
    root_prompt = str(prompts.get("root") or "")
    if "<examples" in root_prompt.lower() or "example" in root_prompt.lower():
        diagnostics.append(
            ContextDiagnostic(
                severity="info",
                category="instruction_hierarchy",
                component_id="instructions",
                message="Root prompt includes examples alongside instructions.",
                recommendation="Keep instructions, context, and examples visibly separated so profiles can include or omit examples deliberately.",
            )
        )

    compaction = config.get("compaction") if isinstance(config.get("compaction"), dict) else {}
    if not compaction.get("enabled") and utilization > 0.50:
        diagnostics.append(
            ContextDiagnostic(
                severity="warning",
                category="compaction",
                component_id="context_strategy",
                message="Compaction is disabled while the preview is already using more than half the budget.",
                recommendation="Enable compaction or add a retention plan before long-horizon evals.",
            )
        )

    memory_policy = config.get("memory_policy") if isinstance(config.get("memory_policy"), dict) else {}
    max_entries = int(memory_policy.get("max_entries") or 0)
    if memory_policy.get("preload") and max_entries > 50:
        diagnostics.append(
            ContextDiagnostic(
                severity="warning",
                category="memory",
                component_id="context_strategy",
                message=f"Memory preload allows up to {max_entries} entries.",
                recommendation="Prefer targeted memory recall or a smaller preload cap for production agents.",
            )
        )

    if profile.include_project_memory and not project_memory_text.strip():
        diagnostics.append(
            ContextDiagnostic(
                severity="info",
                category="memory",
                component_id="project_memory",
                message="Project memory is enabled for this profile but no memory text was found.",
                recommendation="Add compact known-good patterns, known-bad patterns, and team preferences to AGENTLAB.md.",
            )
        )

    largest = max((component for component in components if component.included), key=lambda item: item.token_count, default=None)
    if largest and total_tokens and largest.token_count / total_tokens > 0.60:
        diagnostics.append(
            ContextDiagnostic(
                severity="info",
                category="shape",
                component_id=largest.component_id,
                message=f"{largest.label} accounts for most of the previewed context.",
                recommendation="Confirm this component is high-signal; large single components are harder for agents to navigate.",
            )
        )

    return diagnostics


def _status_from_diagnostics(diagnostics: list[ContextDiagnostic]) -> str:
    if any(item.severity == "critical" for item in diagnostics):
        return "over_budget"
    if any(item.severity == "warning" for item in diagnostics):
        return "watch"
    return "healthy"


def _format_prompts(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    sections = []
    for name, prompt in value.items():
        text = str(prompt).strip()
        if text:
            sections.append(f"## {name}\n{text}")
    return "\n\n".join(sections)


def _extract_examples(config: dict[str, Any]) -> str:
    chunks: list[str] = []
    examples = config.get("examples") or config.get("few_shot") or config.get("few_shot_examples")
    if examples:
        chunks.append(_format_yaml_like(examples))

    prompts = config.get("prompts") if isinstance(config.get("prompts"), dict) else {}
    for name, prompt in prompts.items():
        text = str(prompt)
        lower = text.lower()
        if "<examples" in lower:
            chunks.append(f"## {name} prompt examples\n{text}")
        elif "example" in lower:
            lines = [line for line in text.splitlines() if "example" in line.lower()]
            if lines:
                chunks.append(f"## {name} prompt example lines\n" + "\n".join(lines))
    return "\n\n".join(chunks)


def _format_tools(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    lines: list[str] = []
    for name, spec in value.items():
        if isinstance(spec, dict):
            enabled = spec.get("enabled", True)
            if not enabled:
                continue
            description = str(spec.get("description") or spec.get("summary") or "").strip()
            timeout = spec.get("timeout_ms")
            detail = description or "No description provided."
            suffix = f" timeout_ms={timeout}" if timeout is not None else ""
            lines.append(f"- {name}: {detail}{suffix}")
        elif spec:
            lines.append(f"- {name}: enabled")
    return "\n".join(lines)


def _format_context_strategy(config: dict[str, Any], profile: ContextProfile) -> str:
    payload = {
        "profile": {
            "name": profile.name,
            "token_budget": profile.token_budget,
            "target_utilization": profile.target_utilization,
            "compaction_trigger": profile.compaction_trigger,
            "retention_ratio": profile.retention_ratio,
        },
        "context_caching": config.get("context_caching", {}),
        "compaction": config.get("compaction", {}),
        "memory_policy": config.get("memory_policy", {}),
    }
    return yaml.safe_dump(payload, sort_keys=False)


def _format_recent_failures(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return ""
    lines: list[str] = []
    for index, item in enumerate(failures[:5], start=1):
        trace_id = item.get("trace_id", "unknown")
        reason = item.get("reason") or item.get("error_message") or item.get("failure") or "failure"
        lines.append(f"{index}. {trace_id}: {reason}")
    return "\n".join(lines)


def _format_yaml_like(value: Any) -> str:
    if value in (None, {}, []):
        return ""
    if isinstance(value, str):
        return value
    return yaml.safe_dump(value, sort_keys=False).strip()


def _compact_preview(text: str, limit: int = 360) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."
