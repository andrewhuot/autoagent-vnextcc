"""Workspace-facing build config mapping, persistence, and preview helpers."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent import create_eval_agent
from cli.mode import load_runtime_with_builder_live_preference
from cli.workspace import AgentLabWorkspace, discover_workspace
from deployer import Deployer
from logger.store import ConversationStore
from shared.build_artifact_store import BuildArtifactStore
from shared.contracts import BuildArtifact


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "when",
    "with",
    "you",
    "your",
}

_ORDERS_HINTS = {
    "address",
    "arrival",
    "book",
    "booking",
    "cancel",
    "cancellation",
    "deliver",
    "delivery",
    "flight",
    "gate",
    "invoice",
    "order",
    "payment",
    "refund",
    "reservation",
    "return",
    "ship",
    "shipping",
    "status",
    "tracking",
}
_RECOMMENDATION_HINTS = {
    "alternative",
    "compare",
    "comparison",
    "demo",
    "discover",
    "fit",
    "lead",
    "prospect",
    "qualify",
    "recommend",
    "sales",
    "suggest",
}
_SUPPORT_HINTS = {
    "bug",
    "complaint",
    "damage",
    "disruption",
    "error",
    "escalate",
    "hardware",
    "help",
    "issue",
    "password",
    "policy",
    "problem",
    "safety",
    "support",
    "troubleshoot",
    "vip",
    "vpn",
}


@dataclass(slots=True)
class PreviewResult:
    """Preview one sample conversation against a generated candidate config."""

    response: str
    tool_calls: list[dict[str, Any]]
    latency_ms: float
    token_count: int
    specialist_used: str
    mock_mode: bool
    mock_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe preview payload."""
        return {
            "response": self.response,
            "tool_calls": self.tool_calls,
            "latency_ms": self.latency_ms,
            "token_count": self.token_count,
            "specialist_used": self.specialist_used,
            "mock_mode": self.mock_mode,
            "mock_reasons": self.mock_reasons,
        }


@dataclass(slots=True)
class SaveResult:
    """Describe the files written when a generated config is saved."""

    artifact_id: str
    config_path: str
    config_version: int
    eval_cases_path: str
    runtime_config_path: str
    workspace_path: str
    actual_config_yaml: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe save result payload."""
        return {
            "artifact_id": self.artifact_id,
            "config_path": self.config_path,
            "config_version": self.config_version,
            "eval_cases_path": self.eval_cases_path,
            "runtime_config_path": self.runtime_config_path,
            "workspace_path": self.workspace_path,
            "actual_config_yaml": self.actual_config_yaml,
        }


def generated_config_to_runtime_config(
    generated_config: dict[str, Any],
    *,
    source_prompt: str | None = None,
    transcript_report_id: str | None = None,
    builder_session_id: str | None = None,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map the Build UI contract into the real AgentLab runtime config shape.

    WHY: The Build UI surfaces richer preview data than the current eval/runtime
    schema accepts directly. We preserve the exact requested build details under
    `journey_build` while projecting the runnable portions into the existing
    config fields used by `agentlab eval run`.
    """
    config = copy.deepcopy(base_config or _load_base_agent_config())
    metadata = generated_config.get("metadata") if isinstance(generated_config.get("metadata"), dict) else {}
    agent_name = str(metadata.get("agent_name") or "AgentLab")
    model = str(generated_config.get("model") or config.get("model") or "gpt-4o")
    system_prompt = str(generated_config.get("system_prompt") or config.get("prompts", {}).get("root") or "").strip()

    config["model"] = model
    prompts = config.setdefault("prompts", {})
    prompts["root"] = system_prompt
    prompts.update(_build_specialist_prompts(system_prompt, generated_config))

    routing = config.setdefault("routing", {})
    routing["rules"] = _build_runtime_routing_rules(generated_config, routing.get("rules"))

    tools = config.setdefault("tools", {})
    _apply_builtin_tool_flags(tools, generated_config)

    config["journey_build"] = {
        "agent_name": agent_name,
        "model": model,
        "source_prompt": source_prompt or "",
        "transcript_report_id": transcript_report_id or "",
        "builder_session_id": builder_session_id or "",
        "system_prompt": system_prompt,
        "tools": copy.deepcopy(generated_config.get("tools", [])),
        "routing_rules": copy.deepcopy(generated_config.get("routing_rules", [])),
        "policies": copy.deepcopy(generated_config.get("policies", [])),
        "eval_criteria": copy.deepcopy(generated_config.get("eval_criteria", [])),
        "metadata": copy.deepcopy(metadata),
    }
    return config


def generated_config_to_yaml(
    generated_config: dict[str, Any],
    *,
    source_prompt: str | None = None,
    transcript_report_id: str | None = None,
    builder_session_id: str | None = None,
    base_config: dict[str, Any] | None = None,
) -> str:
    """Render the actual runnable config YAML for a generated Build draft."""
    runtime_config = generated_config_to_runtime_config(
        generated_config,
        source_prompt=source_prompt,
        transcript_report_id=transcript_report_id,
        builder_session_id=builder_session_id,
        base_config=base_config,
    )
    return yaml.safe_dump(runtime_config, sort_keys=False)


def preview_generated_config(generated_config: dict[str, Any], user_message: str) -> PreviewResult:
    """Run one sample message through the generated candidate config.

    WHY: The Build tab needs a truthful preview path that exercises the same
    runtime adapter used by evals instead of inventing canned sample replies.
    """
    workspace = _require_workspace()
    runtime = load_runtime_with_builder_live_preference(str(workspace.runtime_config_path))
    actual_config = generated_config_to_runtime_config(generated_config)
    eval_agent = create_eval_agent(runtime, default_config=actual_config)
    preview = eval_agent.run(user_message, config=actual_config)
    return PreviewResult(
        response=str(preview.get("response") or ""),
        tool_calls=list(preview.get("tool_calls") or []),
        latency_ms=float(preview.get("latency_ms") or 0.0),
        token_count=int(preview.get("token_count") or 0),
        specialist_used=str(preview.get("specialist_used") or "support"),
        mock_mode=bool(getattr(eval_agent, "mock_mode", False)),
        mock_reasons=list(getattr(eval_agent, "mock_mode_messages", []) or []),
    )


def persist_generated_config(
    generated_config: dict[str, Any],
    *,
    artifact_store: BuildArtifactStore,
    source: str,
    source_prompt: str | None = None,
    transcript_report_id: str | None = None,
    builder_session_id: str | None = None,
) -> SaveResult:
    """Save a generated Build config into the real workspace/versioning path.

    WHY: The CLI already consumes `configs/` plus workspace metadata, so the UI
    should save into the same files instead of downloading a parallel preview-only
    artifact that `agentlab eval run` cannot discover.
    """
    workspace = _require_workspace()
    workspace.ensure_structure()

    store = ConversationStore(db_path=str(workspace.conversation_db))
    deployer = Deployer(configs_dir=str(workspace.configs_dir), store=store)
    active = workspace.resolve_active_config()
    actual_config = generated_config_to_runtime_config(
        generated_config,
        source_prompt=source_prompt,
        transcript_report_id=transcript_report_id,
        builder_session_id=builder_session_id,
        base_config=(active.config if active is not None else None),
    )

    saved = deployer.version_manager.save_version(
        actual_config,
        scores={"composite": 0.0},
        status="candidate",
    )
    config_path = workspace.configs_dir / saved.filename
    workspace.metadata.agent_name = str(
        (generated_config.get("metadata") or {}).get("agent_name") or workspace.metadata.agent_name
    )
    workspace.set_active_config(saved.version, filename=saved.filename)

    eval_cases_path = workspace.cases_dir / "generated_build.yaml"
    _write_generated_eval_cases(eval_cases_path, generated_config)

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    actual_config_yaml = yaml.safe_dump(actual_config, sort_keys=False)
    artifact = artifact_store.save_latest(
        BuildArtifact(
            id=f"build-{saved.version:03d}-{datetime.now(tz=timezone.utc).strftime('%H%M%S')}",
            created_at=now_iso,
            updated_at=now_iso,
            source=source,
            status="complete",
            config_yaml=actual_config_yaml,
            prompt_used=source_prompt,
            transcript_report_id=transcript_report_id,
            builder_session_id=builder_session_id,
            eval_draft=str(eval_cases_path),
            starter_config_path=str(config_path),
            selector="latest",
            metadata={
                "title": str((generated_config.get("metadata") or {}).get("agent_name") or "Build Config"),
                "summary": "Saved from the Build workspace into the active AgentLab workspace.",
                "generated_config": copy.deepcopy(generated_config),
            },
        )
    )

    return SaveResult(
        artifact_id=str(artifact["id"]),
        config_path=str(config_path),
        config_version=saved.version,
        eval_cases_path=str(eval_cases_path),
        runtime_config_path=str(workspace.runtime_config_path),
        workspace_path=str(workspace.root),
        actual_config_yaml=actual_config_yaml,
    )


def _require_workspace() -> AgentLabWorkspace:
    """Resolve the current workspace or fail with a helpful error.

    WHY: Build saves and previews are only meaningful when they target a real
    AgentLab workspace with `configs/`, `evals/`, and runtime metadata.
    """
    workspace = discover_workspace()
    if workspace is None:
        raise RuntimeError("No AgentLab workspace found. Open Setup or run `agentlab init` first.")
    return workspace


def _load_base_agent_config() -> dict[str, Any]:
    """Load the default agent config scaffold shipped with the repo."""
    base_config_path = Path(__file__).resolve().parents[1] / "agent" / "config" / "base_config.yaml"
    return yaml.safe_load(base_config_path.read_text(encoding="utf-8")) or {}


def _build_specialist_prompts(system_prompt: str, generated_config: dict[str, Any]) -> dict[str, str]:
    """Create specialist prompts that stay aligned with the generated root prompt."""
    policy_names = [str(policy.get("name") or "") for policy in generated_config.get("policies", []) if isinstance(policy, dict)]
    policy_summary = ", ".join(name for name in policy_names if name) or "the configured policies"

    support = (
        f"{system_prompt}\n\n"
        "Support focus: handle general support questions, escalations, troubleshooting, and sensitive edge cases. "
        f"Honor {policy_summary} when choosing the next step."
    ).strip()
    orders = (
        f"{system_prompt}\n\n"
        "Operations focus: handle status checks, bookings, orders, refunds, returns, cancellations, and verification-heavy workflows carefully."
    ).strip()
    recommendations = (
        f"{system_prompt}\n\n"
        "Guidance focus: handle discovery, recommendations, qualification, and comparison-style requests with one useful clarifying question when needed."
    ).strip()

    return {
        "support": support,
        "orders": orders,
        "recommendations": recommendations,
    }


def _build_runtime_routing_rules(
    generated_config: dict[str, Any],
    base_rules: Any,
) -> list[dict[str, Any]]:
    """Project rich Build routing hints onto the current runtime routing schema."""
    grouped: dict[str, dict[str, Any]] = {}
    for specialist in ("support", "orders", "recommendations"):
        grouped[specialist] = {
            "specialist": specialist,
            "keywords": set(),
            "patterns": set(),
        }

    for rule in base_rules or []:
        if not isinstance(rule, dict):
            continue
        specialist = str(rule.get("specialist") or "support")
        bucket = grouped.setdefault(
            specialist,
            {"specialist": specialist, "keywords": set(), "patterns": set()},
        )
        bucket["keywords"].update(str(item) for item in rule.get("keywords", []) if str(item).strip())
        bucket["patterns"].update(str(item) for item in rule.get("patterns", []) if str(item).strip())

    source_texts: list[str] = [str(generated_config.get("system_prompt") or "")]
    for collection_name in ("routing_rules", "tools", "policies", "eval_criteria"):
        for item in generated_config.get(collection_name, []):
            if not isinstance(item, dict):
                continue
            source_texts.extend(str(value) for value in item.values() if isinstance(value, (str, int, float)))

    for text in source_texts:
        tokens = _extract_tokens(text)
        if not tokens:
            continue
        specialist = _infer_specialist(text, tokens)
        grouped[specialist]["keywords"].update(tokens)
        pattern = _pattern_from_text(text)
        if pattern:
            grouped[specialist]["patterns"].add(pattern)

    ordered_rules: list[dict[str, Any]] = []
    for specialist in ("support", "orders", "recommendations"):
        bucket = grouped[specialist]
        ordered_rules.append(
            {
                "specialist": specialist,
                "keywords": sorted(bucket["keywords"]),
                "patterns": sorted(bucket["patterns"]),
            }
        )
    return ordered_rules


def _apply_builtin_tool_flags(tools: dict[str, Any], generated_config: dict[str, Any]) -> None:
    """Toggle built-in runtime tool flags based on requested Build tools."""
    tool_text = " ".join(
        str(value)
        for item in generated_config.get("tools", [])
        if isinstance(item, dict)
        for value in item.values()
        if isinstance(value, str)
    ).lower()

    if isinstance(tools.get("catalog"), dict):
        tools["catalog"]["enabled"] = any(token in tool_text for token in ("catalog", "product", "recommend", "compare", "prospect", "lead"))
    if isinstance(tools.get("orders_db"), dict):
        tools["orders_db"]["enabled"] = any(token in tool_text for token in ("order", "refund", "shipping", "booking", "flight", "reservation", "status"))
    if isinstance(tools.get("faq"), dict):
        tools["faq"]["enabled"] = any(token in tool_text for token in ("faq", "knowledge", "policy", "help", "article"))


def _extract_tokens(text: str) -> list[str]:
    """Return meaningful lowercase routing tokens from free-form text."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]+", text.lower()):
        token = raw.strip("_-'")
        if len(token) < 3 or token in _STOP_WORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token.replace("_", " "))
    return tokens[:30]


def _pattern_from_text(text: str) -> str:
    """Return one compact pattern string extracted from a longer config fragment."""
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    if len(normalized) > 80:
        normalized = normalized[:77].rstrip() + "..."
    return normalized


def _infer_specialist(text: str, tokens: list[str]) -> str:
    """Classify free-form build hints into the existing runtime specialists."""
    lowered = text.lower()
    token_set = {token.lower() for token in tokens}
    order_score = sum(1 for token in token_set if token in _ORDERS_HINTS) + sum(
        1 for hint in _ORDERS_HINTS if hint in lowered
    )
    recommendation_score = sum(1 for token in token_set if token in _RECOMMENDATION_HINTS) + sum(
        1 for hint in _RECOMMENDATION_HINTS if hint in lowered
    )
    support_score = sum(1 for token in token_set if token in _SUPPORT_HINTS) + sum(
        1 for hint in _SUPPORT_HINTS if hint in lowered
    )

    if recommendation_score > max(order_score, support_score):
        return "recommendations"
    if order_score >= support_score:
        return "orders"
    return "support"


def _write_generated_eval_cases(path: Path, generated_config: dict[str, Any]) -> None:
    """Write a small runnable eval suite derived from the generated config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    routing_rules = [item for item in generated_config.get("routing_rules", []) if isinstance(item, dict)]
    for index, rule in enumerate(routing_rules[:3], start=1):
        source_text = f"{rule.get('condition', '')} {rule.get('action', '')}"
        tokens = _extract_tokens(source_text)
        specialist = _infer_specialist(source_text, tokens)
        leading_token = tokens[0] if tokens else specialist
        cases.append(
            {
                "id": f"build_{index:03d}",
                "category": "generated_build",
                "user_message": f"I need help with {leading_token}.",
                "expected_specialist": specialist,
                "expected_behavior": "answer",
                "expected_keywords": tokens[:3] or [specialist],
                "expected_notes": str(rule.get("condition") or rule.get("action") or "Generated routing case."),
            }
        )

    if not cases:
        criteria = [item for item in generated_config.get("eval_criteria", []) if isinstance(item, dict)]
        for index, criterion in enumerate(criteria[:3], start=1):
            description = str(criterion.get("description") or criterion.get("name") or "general support")
            tokens = _extract_tokens(description)
            specialist = _infer_specialist(description, tokens)
            cases.append(
                {
                    "id": f"build_{index:03d}",
                    "category": "generated_build",
                    "user_message": f"Please help with {tokens[0] if tokens else 'this request'}.",
                    "expected_specialist": specialist,
                    "expected_behavior": "answer",
                    "expected_keywords": tokens[:3] or [specialist],
                    "expected_notes": description,
                }
            )

    if not cases:
        cases = [
            {
                "id": "build_001",
                "category": "generated_build",
                "user_message": "Can you help me with this request?",
                "expected_specialist": "support",
                "expected_behavior": "answer",
                "expected_keywords": ["help", "support"],
                "expected_notes": "Fallback generated case when no richer build hints were available.",
            }
        ]

    path.write_text(yaml.safe_dump(cases, sort_keys=False), encoding="utf-8")
