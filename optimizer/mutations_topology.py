"""Workflow and topology optimization operators (experimental).

These operators analyze and modify the agent's routing topology and workflow
structure. All topology mutations are experimental and require manual PR
review — they never support auto-deployment.
"""

from __future__ import annotations

import copy
from typing import Any

from optimizer.mutations import (
    MutationOperator,
    MutationRegistry,
    MutationSurface,
    RiskClass,
)

EXPERIMENTAL: bool = True
"""Module-level flag indicating these operators are experimental."""

_TOPOLOGY_MARKER = "_experimental_topology_change"


def _apply_detect_transfer_loops(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Analyze routing config for potential transfer loops.

    Stub: marks the config with an experimental topology change marker
    indicating loop detection was run.
    """
    cfg = copy.deepcopy(config)
    cfg[_TOPOLOGY_MARKER] = {
        "operator": "detect_transfer_loops",
        "status": "analyzed",
        "loops_detected": [],
    }
    return cfg


def _apply_reduce_unnecessary_parallelism(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Simplify over-complex routing by reducing unnecessary parallelism.

    Stub: marks the config with an experimental topology change marker
    indicating parallelism reduction was attempted.
    """
    cfg = copy.deepcopy(config)
    cfg[_TOPOLOGY_MARKER] = {
        "operator": "reduce_unnecessary_parallelism",
        "status": "analyzed",
        "reductions": [],
    }
    return cfg


def _apply_add_deterministic_steps(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Add missing validation or preprocessing steps to the workflow.

    Stub: marks the config with an experimental topology change marker
    indicating deterministic steps were proposed.
    """
    cfg = copy.deepcopy(config)
    cfg[_TOPOLOGY_MARKER] = {
        "operator": "add_deterministic_steps",
        "status": "analyzed",
        "proposed_steps": [],
    }
    return cfg


def register_topology_operators(registry: MutationRegistry) -> None:
    """Register all topology optimization operators.

    All topology operators have supports_autodeploy=False because topology
    changes must always go through PR review.
    """
    registry.register(
        MutationOperator(
            name="detect_transfer_loops",
            surface=MutationSurface.routing,
            risk_class=RiskClass.high,
            preconditions=["routing rules exist in config"],
            validator=lambda cfg: _TOPOLOGY_MARKER in cfg,
            rollback_strategy="remove loop detection annotations",
            estimated_eval_cost=0.01,
            supports_autodeploy=False,
            description=(
                "Analyze routing config for potential transfer loops "
                "between specialist agents. (Experimental)"
            ),
            apply=_apply_detect_transfer_loops,
            ready=False,
        )
    )

    registry.register(
        MutationOperator(
            name="reduce_unnecessary_parallelism",
            surface=MutationSurface.workflow,
            risk_class=RiskClass.high,
            preconditions=["routing rules exist in config"],
            validator=lambda cfg: _TOPOLOGY_MARKER in cfg,
            rollback_strategy="revert to original routing topology",
            estimated_eval_cost=0.02,
            supports_autodeploy=False,
            description=(
                "Simplify over-complex routing by reducing unnecessary "
                "parallel branches. (Experimental)"
            ),
            apply=_apply_reduce_unnecessary_parallelism,
            ready=False,
        )
    )

    registry.register(
        MutationOperator(
            name="add_deterministic_steps",
            surface=MutationSurface.workflow,
            risk_class=RiskClass.medium,
            preconditions=["workflow definition exists in config"],
            validator=lambda cfg: _TOPOLOGY_MARKER in cfg,
            rollback_strategy="remove added deterministic steps",
            estimated_eval_cost=0.01,
            supports_autodeploy=False,
            description=(
                "Add missing validation or preprocessing steps to "
                "the agent workflow. (Experimental)"
            ),
            apply=_apply_add_deterministic_steps,
            ready=False,
        )
    )
