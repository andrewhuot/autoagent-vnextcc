"""Tool registry exposing Workbench in-process commands as LLM tools (R7.1).

The registry is a pure data structure: it maps a tool name to a
:class:`ToolDescriptor` wrapping an in-process ``run_*_in_process``
function, the JSON-schema the model sees, and a result shaper that
converts the function's frozen dataclass return into a JSON-safe dict.

The registry intentionally does NOT consult the permission table.
Permission checks are the conversation loop's responsibility — keeping
them separate means the registry stays a pure data structure that
tests can build without touching policy state.

The seven in-process commands all declare ``on_event`` (and usually
``text_writer``) as keyword-only parameters. Those are side-channels
used by the CLI/TUI for progress streaming — the LLM must never be
asked to supply them. :meth:`ToolRegistry.call` auto-injects a no-op
``on_event`` and ``text_writer=None`` so the model only needs to pass
domain arguments (``config_path``, ``attempt_id``, etc.).
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable, Mapping


ToolCallable = Callable[..., Any]
ResultShaper = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class ToolDescriptor:
    """One LLM-callable tool wrapping an in-process command."""

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolCallable
    shape_result: ResultShaper


def _jsonify(value: Any) -> Any:
    """Recursively convert tuples/frozensets/sets/dataclasses to JSON-safe values.

    ``dataclasses.asdict`` leaves ``tuple[str, ...]`` as tuples and
    ``frozenset`` as frozensets. Neither is JSON-encodable by the stdlib
    default encoder, so we normalize to lists here.
    """
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_jsonify(v) for v in value]
    return value


def dataclass_to_jsonsafe(value: Any) -> dict[str, Any]:
    """Default result shaper: dataclass -> nested dict with JSON-safe values.

    ``dataclasses.asdict`` recursively converts nested dataclasses; we
    post-process the tree to turn tuples/sets into lists.
    """
    if is_dataclass(value) and not isinstance(value, type):
        raw = asdict(value)
    elif isinstance(value, dict):
        raw = value
    else:
        # Best-effort fallback: wrap non-dict, non-dataclass returns.
        return {"value": _jsonify(value)}
    return _jsonify(raw)  # type: ignore[return-value]


@dataclass
class ToolRegistry:
    """Mutable registry of :class:`ToolDescriptor` keyed by tool name."""

    _tools: dict[str, ToolDescriptor] = field(default_factory=dict)

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._tools:
            raise ValueError(f"Tool already registered: {descriptor.name}")
        self._tools[descriptor.name] = descriptor

    def get(self, name: str) -> ToolDescriptor:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list(self) -> list[ToolDescriptor]:
        return list(self._tools.values())

    def call(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke the named tool with ``args`` and return the shaped result.

        Raises:
            KeyError: if ``name`` is not a registered tool.
            TypeError: if the filtered args don't match ``fn``'s signature
                (e.g. missing a required parameter).

        The conversation loop catches both and feeds an error back to the
        model. Unknown keys in ``args`` are silently dropped so a model
        hallucinating an extra parameter doesn't wedge the call.
        """
        descriptor = self.get(name)
        sig = inspect.signature(descriptor.fn)
        accepted: dict[str, Any] = {
            k: v for k, v in args.items() if k in sig.parameters
        }
        if "on_event" in sig.parameters and "on_event" not in accepted:
            accepted["on_event"] = lambda _e: None
        if "text_writer" in sig.parameters and "text_writer" not in accepted:
            accepted["text_writer"] = None
        result = descriptor.fn(**accepted)
        return descriptor.shape_result(result)


# ---------------------------------------------------------------------------
# Hand-written JSON schemas for the seven in-process commands.
# Each schema exposes ONLY domain-level arguments; ``on_event`` and
# ``text_writer`` are deliberately omitted and auto-injected by ``.call()``.
# ---------------------------------------------------------------------------


_EVAL_RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": "Path to the agent config YAML. Defaults to the active workspace config.",
        },
        "suite": {
            "type": "string",
            "description": "Eval suite name (e.g. 'core', 'safety'). Optional.",
        },
        "category": {
            "type": "string",
            "description": "Filter eval cases by category. Optional.",
        },
        "dataset": {
            "type": "string",
            "description": "Dataset name to evaluate against. Optional.",
        },
        "dataset_split": {
            "type": "string",
            "description": "Dataset split selector (default 'all').",
            "default": "all",
        },
        "output_path": {
            "type": "string",
            "description": "Write a JSON artifact of the run to this path. Optional.",
        },
        "instruction_overrides_path": {
            "type": "string",
            "description": "Path to an instruction-overrides YAML. Optional.",
        },
        "real_agent": {
            "type": "boolean",
            "description": "Force the real agent (disables mock fallback).",
            "default": False,
        },
        "force_mock": {
            "type": "boolean",
            "description": "Force mock mode regardless of live provider availability.",
            "default": False,
        },
        "require_live": {
            "type": "boolean",
            "description": "Abort if live providers are unavailable (no silent mock fallback).",
            "default": False,
        },
        "strict_live": {
            "type": "boolean",
            "description": "Require live mode AND reject warnings indicating partial fallback.",
            "default": False,
        },
    },
}


_DEPLOY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workflow": {
            "type": "string",
            "description": "Workflow selector (e.g. 'canary', 'rollback'). Optional.",
        },
        "config_version": {
            "type": "integer",
            "description": "Deploy a specific config version number. Optional.",
        },
        "strategy": {
            "type": "string",
            "description": "Deploy strategy: 'canary' (default) or 'immediate'.",
            "default": "canary",
        },
        "strict_live": {
            "type": "boolean",
            "description": "Abort the deploy if any upstream ran in mock mode.",
            "default": False,
        },
        "attempt_id": {
            "type": "string",
            "description": "Optimization attempt id to deploy. Optional.",
        },
        "dry_run": {
            "type": "boolean",
            "description": "Plan only — do not mutate production state.",
            "default": False,
        },
        "acknowledge": {
            "type": "boolean",
            "description": "Acknowledge an interactive gate prompt.",
            "default": False,
        },
        "auto_review": {
            "type": "boolean",
            "description": "Auto-approve pending change cards before deploying.",
            "default": False,
        },
        "force_deploy_degraded": {
            "type": "boolean",
            "description": "Override the degraded-verdict gate (requires force_reason).",
            "default": False,
        },
        "force_reason": {
            "type": "string",
            "description": "Written justification (>=10 chars) required with force_deploy_degraded.",
        },
        "target": {
            "type": "string",
            "description": "Deploy target name (default 'agentlab').",
            "default": "agentlab",
        },
        "configs_dir": {
            "type": "string",
            "description": "Override the configs directory root. Optional.",
        },
        "db": {
            "type": "string",
            "description": "Override the conversation/agent DB path. Optional.",
        },
        "release_experiment_id": {
            "type": "string",
            "description": "Associate the deploy with a release experiment. Optional.",
        },
    },
}


_IMPROVE_RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": "Path to the agent config YAML to optimize. Required.",
        },
        "cycles": {
            "type": "integer",
            "description": "Number of optimization cycles to run (default 1).",
            "default": 1,
        },
        "mode": {
            "type": "string",
            "description": "Optional optimizer mode selector.",
        },
        "strict_live": {
            "type": "boolean",
            "description": "Require live mode for embedded eval runs.",
            "default": False,
        },
        "auto": {
            "type": "boolean",
            "description": "Auto-accept proposals that pass gates without asking.",
            "default": False,
        },
    },
    "required": ["config_path"],
}


_IMPROVE_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "description": "Filter by classified status (e.g. 'proposed', 'promoted', 'rejected').",
        },
        "reason": {
            "type": "string",
            "description": "Filter rejected attempts by rejection reason.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum attempts to return (default 20).",
            "default": 20,
        },
        "memory_db": {
            "type": "string",
            "description": "Override OptimizationMemory DB path. Optional.",
        },
        "lineage_db": {
            "type": "string",
            "description": "Override ImprovementLineageStore DB path. Optional.",
        },
    },
}


_IMPROVE_SHOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": "Optimization attempt id (or unique prefix). Required.",
        },
        "memory_db": {
            "type": "string",
            "description": "Override OptimizationMemory DB path. Optional.",
        },
        "lineage_db": {
            "type": "string",
            "description": "Override ImprovementLineageStore DB path. Optional.",
        },
    },
    "required": ["attempt_id"],
}


_IMPROVE_DIFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": "Optimization attempt id (or unique prefix). Required.",
        },
        "memory_db": {
            "type": "string",
            "description": "Override OptimizationMemory DB path. Optional.",
        },
    },
    "required": ["attempt_id"],
}


_IMPROVE_ACCEPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempt_id": {
            "type": "string",
            "description": "Optimization attempt id (or unique prefix) to promote. Required.",
        },
        "strategy": {
            "type": "string",
            "description": "Deploy strategy: 'canary' (default) or 'immediate'.",
            "default": "canary",
        },
        "memory_db": {
            "type": "string",
            "description": "Override OptimizationMemory DB path. Optional.",
        },
        "lineage_db": {
            "type": "string",
            "description": "Override ImprovementLineageStore DB path. Optional.",
        },
    },
    "required": ["attempt_id"],
}


# Hand-written descriptions — each mentions side-effects and cost class
# so the model can reason about when to call the tool.
_DESCRIPTIONS: dict[str, str] = {
    "eval_run": (
        "Run an eval suite against the current or specified agent config "
        "and return composite score, mode, status, and warnings. This is "
        "a 'run' operation — it costs LLM tokens and writes to the "
        "eval-run store."
    ),
    "deploy": (
        "Promote an attempt or config version to canary or full "
        "deployment. Mutates production state — call only after the user "
        "has explicitly asked to deploy."
    ),
    "improve_run": (
        "Run an optimization attempt against the given config. Spawns "
        "LLM-driven proposal cycles. Costs tokens; writes a new attempt "
        "to the attempt store."
    ),
    "improve_list": (
        "List recent optimization attempts. Read-only; returns recent "
        "attempt summaries (id, status, score)."
    ),
    "improve_show": (
        "Show full details of one optimization attempt by id (or id "
        "prefix). Read-only."
    ),
    "improve_diff": (
        "Show the config diff produced by one optimization attempt. "
        "Read-only."
    ),
    "improve_accept": (
        "Promote one optimization attempt to the active config. "
        "Mutates workspace state."
    ),
}


def build_default_registry() -> ToolRegistry:
    """Register all 7 in-process commands with hand-written descriptions.

    Imports the ``run_*_in_process`` functions lazily so constructing a
    registry at module import time doesn't drag the full command
    surface into every consumer. Tests can call this function to get a
    fresh registry without leaking global state.
    """
    from cli.commands.deploy import run_deploy_in_process
    from cli.commands.eval import run_eval_in_process
    from cli.commands.improve import (
        run_improve_accept_in_process,
        run_improve_diff_in_process,
        run_improve_list_in_process,
        run_improve_run_in_process,
        run_improve_show_in_process,
    )

    registry = ToolRegistry()

    registry.register(
        ToolDescriptor(
            name="eval_run",
            description=_DESCRIPTIONS["eval_run"],
            input_schema=_EVAL_RUN_SCHEMA,
            fn=run_eval_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="deploy",
            description=_DESCRIPTIONS["deploy"],
            input_schema=_DEPLOY_SCHEMA,
            fn=run_deploy_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="improve_run",
            description=_DESCRIPTIONS["improve_run"],
            input_schema=_IMPROVE_RUN_SCHEMA,
            fn=run_improve_run_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="improve_list",
            description=_DESCRIPTIONS["improve_list"],
            input_schema=_IMPROVE_LIST_SCHEMA,
            fn=run_improve_list_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="improve_show",
            description=_DESCRIPTIONS["improve_show"],
            input_schema=_IMPROVE_SHOW_SCHEMA,
            fn=run_improve_show_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="improve_diff",
            description=_DESCRIPTIONS["improve_diff"],
            input_schema=_IMPROVE_DIFF_SCHEMA,
            fn=run_improve_diff_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )
    registry.register(
        ToolDescriptor(
            name="improve_accept",
            description=_DESCRIPTIONS["improve_accept"],
            input_schema=_IMPROVE_ACCEPT_SCHEMA,
            fn=run_improve_accept_in_process,
            shape_result=dataclass_to_jsonsafe,
        )
    )

    return registry


__all__ = [
    "ToolDescriptor",
    "ToolRegistry",
    "build_default_registry",
    "dataclass_to_jsonsafe",
]
