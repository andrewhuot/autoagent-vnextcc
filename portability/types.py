"""Framework-neutral portability and readiness models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ImportCoverageStatus(str, Enum):
    """How completely a source surface was captured during import."""

    IMPORTED = "imported"
    PARTIAL = "partial"
    REFERENCED = "referenced"
    MISSING = "missing"


class PortabilityStatus(str, Enum):
    """Whether a surfaced construct can be optimized today."""

    OPTIMIZABLE = "optimizable"
    READ_ONLY = "read_only"
    UNSUPPORTED = "unsupported"


class ExportReadinessStatus(str, Enum):
    """Whether a surfaced construct can round-trip back to the source runtime."""

    READY = "ready"
    LOSSY = "lossy"
    BLOCKED = "blocked"


class PortabilitySurface(BaseModel):
    """One modeled source-runtime surface in the portability report."""

    surface_id: str
    label: str
    coverage_status: ImportCoverageStatus = ImportCoverageStatus.MISSING
    portability_status: PortabilityStatus = PortabilityStatus.UNSUPPORTED
    export_status: ExportReadinessStatus = ExportReadinessStatus.BLOCKED
    optimization_surface_id: str = ""
    rationale: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportedCallback(BaseModel):
    """Normalized callback binding discovered during import."""

    name: str
    binding: str
    stage: str
    source_ref: str = ""
    portability_status: PortabilityStatus = PortabilityStatus.READ_ONLY
    export_status: ExportReadinessStatus = ExportReadinessStatus.BLOCKED
    rationale: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportGraphNode(BaseModel):
    """A node in the imported topology graph."""

    node_id: str
    node_type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportGraphEdge(BaseModel):
    """A directed edge in the imported topology graph."""

    source_id: str
    target_id: str
    edge_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportTopologySummary(BaseModel):
    """Compact summary over the imported topology graph."""

    node_count: int = 0
    edge_count: int = 0
    max_depth: int = 0
    agent_count: int = 0
    tool_count: int = 0
    callback_count: int = 0
    flow_count: int = 0
    page_count: int = 0
    intent_count: int = 0
    webhook_count: int = 0
    test_case_count: int = 0
    orchestration_modes: list[str] = Field(default_factory=list)


class ImportTopology(BaseModel):
    """Topology graph plus a precomputed summary."""

    nodes: list[ImportGraphNode] = Field(default_factory=list)
    edges: list[ImportGraphEdge] = Field(default_factory=list)
    summary: ImportTopologySummary = Field(default_factory=ImportTopologySummary)


class OptimizationEligibilityScore(BaseModel):
    """Numeric readiness score with rationale and blockers."""

    score: int = 0
    coverage_score: int = 0
    optimizability_score: int = 0
    export_score: int = 0
    blockers: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class ExportCapabilityRow(BaseModel):
    """One row in the round-trip capability matrix."""

    surface_id: str
    label: str
    status: ExportReadinessStatus = ExportReadinessStatus.BLOCKED
    blockers: list[str] = Field(default_factory=list)
    writable_paths: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExportCapabilityMatrix(BaseModel):
    """Machine-readable export and round-trip readiness summary."""

    status: ExportReadinessStatus = ExportReadinessStatus.BLOCKED
    round_trip_ready: bool = False
    ready_surfaces: list[str] = Field(default_factory=list)
    lossy_surfaces: list[str] = Field(default_factory=list)
    blocked_surfaces: list[str] = Field(default_factory=list)
    surfaces: list[ExportCapabilityRow] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class PortabilitySummary(BaseModel):
    """Aggregate counts over the modeled portability surfaces."""

    total_surfaces: int = 0
    imported_surfaces: int = 0
    optimizable_surfaces: int = 0
    read_only_surfaces: int = 0
    unsupported_surfaces: int = 0
    ready_export_surfaces: int = 0
    lossy_export_surfaces: int = 0
    blocked_export_surfaces: int = 0


class PortabilityReport(BaseModel):
    """Top-level shared portability report for imported runtimes."""

    platform: str
    source: str = ""
    summary: PortabilitySummary = Field(default_factory=PortabilitySummary)
    surfaces: list[PortabilitySurface] = Field(default_factory=list)
    callbacks: list[ImportedCallback] = Field(default_factory=list)
    topology: ImportTopology = Field(default_factory=ImportTopology)
    optimization_eligibility: OptimizationEligibilityScore = Field(default_factory=OptimizationEligibilityScore)
    export_matrix: ExportCapabilityMatrix = Field(default_factory=ExportCapabilityMatrix)
    notes: list[str] = Field(default_factory=list)
