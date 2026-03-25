"""CX Agent Studio integration — import, optimize, export, deploy.

This module provides bidirectional integration between AutoAgent and
Google Cloud CX Agent Studio (Conversational Agents).

Usage:
    from cx_studio import CxAuth, CxClient, CxImporter, CxExporter, CxDeployer
    from cx_studio.types import CxAgentRef, CxWidgetConfig
"""
from __future__ import annotations

from .auth import CxAuth
from .client import CxClient
from .deployer import CxDeployer
from .errors import (
    CxApiError,
    CxAuthError,
    CxExportError,
    CxImportError,
    CxMappingError,
    CxStudioError,
)
from .exporter import CxExporter
from .importer import CxImporter
from .mapper import CxMapper
from .types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEnvironment,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTestCase,
    CxTool,
    CxWidgetConfig,
    DeployResult,
    ExportResult,
    ImportResult,
)

__all__ = [
    "CxAuth",
    "CxClient",
    "CxDeployer",
    "CxExporter",
    "CxImporter",
    "CxMapper",
    # Types
    "CxAgent",
    "CxAgentRef",
    "CxAgentSnapshot",
    "CxEnvironment",
    "CxFlow",
    "CxIntent",
    "CxPlaybook",
    "CxTestCase",
    "CxTool",
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
