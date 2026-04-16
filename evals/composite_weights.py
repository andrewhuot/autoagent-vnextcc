"""Composite-score weight configuration (R3.9).

Moves the quality/safety/latency/cost weight set out of Python class
constants and into a small config surface with yaml loading. Defaults
match the pre-R3 hardcoded values so existing callers keep working.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CompositeWeights:
    """Weight allocation across the 4 composite-score dimensions.

    Defaults mirror the pre-R3 class-constant values on CompositeScorer.
    Frozen so scorer instances can cache a validated weight object safely.
    """

    quality: float = 0.40
    safety: float = 0.25
    latency: float = 0.20
    cost: float = 0.15


def validate_weights(
    weights: CompositeWeights,
    *,
    tolerance: float = 1e-6,
) -> None:
    """Raise ValueError when weights don't sum to 1.0 (within *tolerance*)
    or any individual weight is negative.

    WHY: Composite scoring is only meaningful when the weights form a
    convex combination; off-sum weights silently shift the scale of the
    composite. Validating at load time catches yaml typos before they
    confuse every eval downstream.
    """
    components = {
        "quality": weights.quality,
        "safety": weights.safety,
        "latency": weights.latency,
        "cost": weights.cost,
    }
    for name, value in components.items():
        if value < 0:
            raise ValueError(f"{name} weight must be non-negative, got {value}")
    total = sum(components.values())
    if abs(total - 1.0) > tolerance:
        raise ValueError(
            f"composite weights must sum to 1.0 (tolerance {tolerance}), "
            f"got {total:.6f}"
        )


def load_from_workspace(yaml_path: str | Path) -> CompositeWeights:
    """Load CompositeWeights from ``eval.composite.weights`` in *yaml_path*.

    Missing file, missing section, or missing individual keys all fall back
    to the pre-R3 defaults — never raises on absence.
    """
    path = Path(yaml_path)
    if not path.exists():
        return CompositeWeights()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return CompositeWeights()
    block = ((data.get("eval") or {}).get("composite") or {}).get("weights") or {}
    defaults = CompositeWeights()
    return CompositeWeights(
        quality=float(block.get("quality", defaults.quality)),
        safety=float(block.get("safety", defaults.safety)),
        latency=float(block.get("latency", defaults.latency)),
        cost=float(block.get("cost", defaults.cost)),
    )
