"""CX Studio integration package exports."""

from __future__ import annotations

from .auth import CxAuth
from .client import CxClient
from .errors import (
    CxApiError,
    CxAuthError,
    CxExportError,
    CxImportError,
    CxMappingError,
    CxStudioError,
)
from .types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxDataStore,
    CxDeployment,
    CxDeploymentTarget,
    CxEntityType,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxTool,
    CxToolResource,
    CxToolType,
    CxTransferRule,
    CxWebhook,
    CxWidgetConfig,
    DeployResult,
    ExportResult,
    ImportResult,
)

__all__ = [
    "CxAuth",
    "CxClient",
    "CxAgent",
    "CxAgentRef",
    "CxAgentSnapshot",
    "CxDataStore",
    "CxDeployment",
    "CxDeploymentTarget",
    "CxEntityType",
    "CxEnvironment",
    "CxFlow",
    "CxIntent",
    "CxPage",
    "CxPlaybook",
    "CxTestCase",
    "CxTool",
    "CxToolResource",
    "CxToolType",
    "CxTransferRule",
    "CxWebhook",
    "CxWidgetConfig",
    "DeployResult",
    "ExportResult",
    "ImportResult",
    "CxApiError",
    "CxAuthError",
    "CxExportError",
    "CxImportError",
    "CxMappingError",
    "CxStudioError",
    "CompatibilityMatrix",
    "CompatEntry",
    "CompatStatus",
    "CxDeployer",
    "CxEvalDataset",
    "CxEvalSync",
    "CxExporter",
    "CxImporter",
    "CxMapper",
    "CxValidationResult",
    "CxValidator",
    "CxVersion",
    "CxVersionManager",
]


def __getattr__(name: str):
    """Lazily import heavier CX modules to avoid package import cycles."""

    if name in {"CompatEntry", "CompatibilityMatrix", "CompatStatus"}:
        from .compat import CompatEntry, CompatibilityMatrix, CompatStatus

        return {
            "CompatEntry": CompatEntry,
            "CompatibilityMatrix": CompatibilityMatrix,
            "CompatStatus": CompatStatus,
        }[name]
    if name == "CxDeployer":
        from .deployer import CxDeployer

        return CxDeployer
    if name in {"CxEvalDataset", "CxEvalSync"}:
        from .eval_sync import CxEvalDataset, CxEvalSync

        return {"CxEvalDataset": CxEvalDataset, "CxEvalSync": CxEvalSync}[name]
    if name == "CxExporter":
        from .exporter import CxExporter

        return CxExporter
    if name == "CxImporter":
        from .importer import CxImporter

        return CxImporter
    if name == "CxMapper":
        from .mapper import CxMapper

        return CxMapper
    if name in {"CxValidationResult", "CxValidator"}:
        from .validator import CxValidationResult, CxValidator

        return {"CxValidationResult": CxValidationResult, "CxValidator": CxValidator}[name]
    if name in {"CxVersion", "CxVersionManager"}:
        from .versions import CxVersion, CxVersionManager

        return {"CxVersion": CxVersion, "CxVersionManager": CxVersionManager}[name]
    raise AttributeError(f"module 'cx_studio' has no attribute {name!r}")
