"""Shared helpers for portability and readiness reporting."""

from __future__ import annotations

from portability.types import (
    ExportCapabilityMatrix,
    ExportCapabilityRow,
    ExportReadinessStatus,
    ImportCoverageStatus,
    ImportTopology,
    ImportedCallback,
    OptimizationEligibilityScore,
    ParityStatus,
    PortabilityReport,
    PortabilityStatus,
    PortabilitySummary,
    PortabilitySurface,
)


_COVERAGE_POINTS = {
    ImportCoverageStatus.IMPORTED: 1.0,
    ImportCoverageStatus.PARTIAL: 0.6,
    ImportCoverageStatus.REFERENCED: 0.3,
    ImportCoverageStatus.MISSING: 0.0,
}

_PORTABILITY_POINTS = {
    PortabilityStatus.OPTIMIZABLE: 1.0,
    PortabilityStatus.READ_ONLY: 0.35,
    PortabilityStatus.UNSUPPORTED: 0.0,
}

_EXPORT_POINTS = {
    ExportReadinessStatus.READY: 1.0,
    ExportReadinessStatus.LOSSY: 0.5,
    ExportReadinessStatus.BLOCKED: 0.0,
}


def build_export_matrix(surfaces: list[PortabilitySurface]) -> ExportCapabilityMatrix:
    """Build a machine-readable export capability matrix from surfaced rows."""

    rows: list[ExportCapabilityRow] = []
    ready_surfaces: list[str] = []
    lossy_surfaces: list[str] = []
    blocked_surfaces: list[str] = []

    for surface in surfaces:
        rows.append(
            ExportCapabilityRow(
                surface_id=surface.surface_id,
                label=surface.label,
                status=surface.export_status,
                blockers=list(surface.rationale) if surface.export_status == ExportReadinessStatus.BLOCKED else [],
                notes=list(surface.rationale),
            )
        )
        if surface.export_status == ExportReadinessStatus.READY:
            ready_surfaces.append(surface.surface_id)
        elif surface.export_status == ExportReadinessStatus.LOSSY:
            lossy_surfaces.append(surface.surface_id)
        else:
            blocked_surfaces.append(surface.surface_id)

    if blocked_surfaces and ready_surfaces:
        status = ExportReadinessStatus.LOSSY
    elif blocked_surfaces and not ready_surfaces:
        status = ExportReadinessStatus.BLOCKED
    else:
        status = ExportReadinessStatus.READY

    rationale = [
        f"{len(ready_surfaces)} surfaces are round-trip ready.",
        f"{len(lossy_surfaces)} surfaces are lossy if exported.",
        f"{len(blocked_surfaces)} surfaces cannot be pushed back today.",
    ]

    return ExportCapabilityMatrix(
        status=status,
        round_trip_ready=status == ExportReadinessStatus.READY,
        ready_surfaces=ready_surfaces,
        lossy_surfaces=lossy_surfaces,
        blocked_surfaces=blocked_surfaces,
        surfaces=rows,
        rationale=rationale,
    )


def build_optimization_eligibility(surfaces: list[PortabilitySurface]) -> OptimizationEligibilityScore:
    """Compute a numeric readiness score from surfaced rows."""

    if not surfaces:
        return OptimizationEligibilityScore(
            blockers=["No modeled surfaces were discovered."],
            rationale=["No portability surfaces were detected during import."],
        )

    coverage_score = round(
        sum(_COVERAGE_POINTS[surface.coverage_status] for surface in surfaces) / len(surfaces) * 100
    )
    optimizability_score = round(
        sum(_PORTABILITY_POINTS[surface.portability_status] for surface in surfaces) / len(surfaces) * 100
    )
    export_score = round(
        sum(_EXPORT_POINTS[surface.export_status] for surface in surfaces) / len(surfaces) * 100
    )
    score = round((coverage_score * 0.4) + (optimizability_score * 0.35) + (export_score * 0.25))

    blockers = [
        surface.label
        for surface in surfaces
        if surface.portability_status != PortabilityStatus.OPTIMIZABLE
        or surface.export_status == ExportReadinessStatus.BLOCKED
    ]

    rationale = [
        f"Import coverage score is {coverage_score}/100 across {len(surfaces)} modeled surfaces.",
        f"Optimizability score is {optimizability_score}/100 based on which surfaces are editable today.",
        f"Round-trip export score is {export_score}/100 based on currently supported write-back paths.",
    ]
    if blockers:
        rationale.append(
            "Biggest readiness blockers: " + ", ".join(blockers[:5]) + ("." if len(blockers) <= 5 else ", ...")
        )

    return OptimizationEligibilityScore(
        score=score,
        coverage_score=coverage_score,
        optimizability_score=optimizability_score,
        export_score=export_score,
        blockers=blockers,
        rationale=rationale,
    )


def build_portability_report(
    *,
    platform: str,
    source: str,
    surfaces: list[PortabilitySurface],
    topology: ImportTopology,
    callbacks: list[ImportedCallback] | None = None,
    notes: list[str] | None = None,
) -> PortabilityReport:
    """Build the shared report from surfaced rows and topology."""

    callbacks = callbacks or []
    notes = notes or []
    export_matrix = build_export_matrix(surfaces)
    optimization = build_optimization_eligibility(surfaces)

    summary = PortabilitySummary(
        total_surfaces=len(surfaces),
        imported_surfaces=sum(
            1 for surface in surfaces if surface.coverage_status in {ImportCoverageStatus.IMPORTED, ImportCoverageStatus.PARTIAL}
        ),
        optimizable_surfaces=sum(
            1 for surface in surfaces if surface.portability_status == PortabilityStatus.OPTIMIZABLE
        ),
        read_only_surfaces=sum(
            1 for surface in surfaces if surface.portability_status == PortabilityStatus.READ_ONLY
        ),
        unsupported_surfaces=sum(
            1 for surface in surfaces if surface.portability_status == PortabilityStatus.UNSUPPORTED
        ),
        supported_parity_surfaces=sum(
            1 for surface in surfaces if surface.parity_status == ParityStatus.SUPPORTED
        ),
        partial_parity_surfaces=sum(
            1 for surface in surfaces if surface.parity_status == ParityStatus.PARTIAL
        ),
        read_only_parity_surfaces=sum(
            1 for surface in surfaces if surface.parity_status == ParityStatus.READ_ONLY
        ),
        unsupported_parity_surfaces=sum(
            1 for surface in surfaces if surface.parity_status == ParityStatus.UNSUPPORTED
        ),
        ready_export_surfaces=len(export_matrix.ready_surfaces),
        lossy_export_surfaces=len(export_matrix.lossy_surfaces),
        blocked_export_surfaces=len(export_matrix.blocked_surfaces),
    )

    return PortabilityReport(
        platform=platform,
        source=source,
        summary=summary,
        surfaces=surfaces,
        callbacks=callbacks,
        topology=topology,
        optimization_eligibility=optimization,
        export_matrix=export_matrix,
        notes=notes,
    )
