"""CX Agent Studio integration — import, optimize, export, deploy.

This module provides bidirectional integration between AutoAgent and
Google Cloud CX Agent Studio (Conversational Agents).

Usage:
    from cx_studio import CxAuth, CxClient, CxImporter, CxExporter, CxDeployer
    from cx_studio.types import CxAgentRef, CxWidgetConfig
    from cx_studio.compat import CompatibilityMatrix, CompatStatus
    from cx_studio.validator import CxValidator
    from cx_studio.versions import CxVersionManager
    from cx_studio.eval_sync import CxEvalSync
"""
from __future__ import annotations

from .auth import CxAuth
from .client import CxClient
from .compat import CompatEntry, CompatibilityMatrix, CompatStatus
from .deployer import CxDeployer
from .errors import (
    CxApiError,
    CxAuthError,
    CxExportError,
    CxImportError,
    CxMappingError,
    CxStudioError,
)
from .eval_sync import CxEvalDataset, CxEvalSync
from .exporter import CxExporter
from .importer import CxImporter
from .mapper import CxMapper
from .types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxDeployment,
    CxDeploymentTarget,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTestCase,
    CxTool,
    CxToolResource,
    CxToolType,
    CxTransferRule,
    CxWidgetConfig,
    DeployResult,
    ExportResult,
    ImportResult,
)
from .validator import CxValidationResult, CxValidator
from .versions import CxVersion, CxVersionManager

__all__ = [
    "CxAuth",
    "CxClient",
    "CxDeployer",
    "CxExporter",
    "CxImporter",
    "CxMapper",
    # Compatibility matrix
    "CompatEntry",
    "CompatibilityMatrix",
    "CompatStatus",
    # Eval sync
    "CxEvalDataset",
    "CxEvalSync",
    # Validator
    "CxValidationResult",
    "CxValidator",
    # Versions
    "CxVersion",
    "CxVersionManager",
    # Types
    "CxAgent",
    "CxAgentRef",
    "CxAgentSnapshot",
    "CxDeployment",
    "CxDeploymentTarget",
    "CxEnvironment",
    "CxFlow",
    "CxIntent",
    "CxPlaybook",
    "CxTestCase",
    "CxTool",
    "CxToolResource",
    "CxToolType",
    "CxTransferRule",
    "CxWidgetConfig",
    "DeployResult",
    "ExportResult",
    "ImportResult",
    # Errors
    "CxApiError",
    "CxAuthError",
    "CxExportError",
    "CxImportError",
    "CxMappingError",
    "CxStudioError",
]
