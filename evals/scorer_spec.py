"""Compiled scorer artifact — output of NL scorer compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml

from core.types import GraderBundle, GraderSpec, GraderType, MetricLayer


@dataclass
class ScorerDimension:
    """A single dimension in a compiled scorer."""

    name: str
    description: str
    grader_type: str  # "deterministic", "llm_judge", "similarity"
    grader_config: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    layer: str = "outcome"  # Maps to MetricLayer
    required: bool = False  # If True, must pass for overall pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "grader_type": self.grader_type,
            "grader_config": self.grader_config,
            "weight": self.weight,
            "layer": self.layer,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScorerDimension:
        return cls(
            name=d["name"],
            description=d["description"],
            grader_type=d["grader_type"],
            grader_config=d.get("grader_config", {}),
            weight=d.get("weight", 1.0),
            layer=d.get("layer", "outcome"),
            required=d.get("required", False),
        )

    def to_grader_spec(self) -> GraderSpec:
        """Convert to a GraderSpec for use in the grader stack."""
        return GraderSpec(
            grader_type=GraderType(self.grader_type),
            grader_id=self.name,
            config=self.grader_config,
            weight=self.weight,
            required=self.required,
        )


@dataclass
class ScorerSpec:
    """A compiled scorer artifact — the output of NL scorer compilation."""

    name: str
    version: int = 1
    dimensions: list[ScorerDimension] = field(default_factory=list)
    source_nl: str = ""  # Original natural language description
    compiled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "source_nl": self.source_nl,
            "compiled_at": self.compiled_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScorerSpec:
        return cls(
            name=d["name"],
            version=d.get("version", 1),
            dimensions=[
                ScorerDimension.from_dict(dim) for dim in d.get("dimensions", [])
            ],
            source_nl=d.get("source_nl", ""),
            compiled_at=d.get("compiled_at", ""),
            metadata=d.get("metadata", {}),
        )

    def to_yaml(self) -> str:
        """Serialize to YAML for version control."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ScorerSpec:
        """Deserialize from YAML."""
        d = yaml.safe_load(yaml_str)
        return cls.from_dict(d)

    def to_grader_bundle(self) -> GraderBundle:
        """Convert to a GraderBundle for use in the eval pipeline."""
        graders = [dim.to_grader_spec() for dim in self.dimensions]
        return GraderBundle(
            graders=graders,
            metadata={"source_scorer": self.name, "version": self.version},
        )

    def total_weight(self) -> float:
        """Sum of all dimension weights."""
        return sum(d.weight for d in self.dimensions)

    def get_dimensions_by_layer(self, layer: str) -> list[ScorerDimension]:
        """Return dimensions for a given metric layer."""
        return [d for d in self.dimensions if d.layer == layer]
