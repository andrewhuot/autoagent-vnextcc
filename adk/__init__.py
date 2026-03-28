"""ADK (Agent Development Kit) integration for AutoAgent.

Provides bidirectional integration with Google's Agent Development Kit:
- Parse ADK Python source code into structured config
- Map ADK agents to AutoAgent surfaces
- Export optimized configs back to ADK source
- Deploy to Cloud Run or Vertex AI
- Execute agents with AutoAgent tracing via the runtime adapter
- Manage session state, lifecycle, and streaming

Public API:
    Types: AdkAgent, AdkAgentTree, AdkTool, AdkAgentRef,
           AdkAgentType, AdkToolType, AdkCallbackSpec, AdkSessionConfig,
           AdkTemplateVar
    Parser: parse_agent_directory
    Mapper: AdkMapper
    Importer: AdkImporter
    Exporter: AdkExporter
    Deployer: AdkDeployer
    Runtime: AdkRuntimeAdapter, AdkExecutionResult
    Callbacks: CallbackRegistry, CallbackType, make_permission_callback
    State: AdkStateManager, StateScope
    Session: AdkSessionManager, AdkSession, SessionStatus
    Streaming: AdkStreamHandler, StreamEvent
    Template vars: resolve_template_vars, extract_template_vars,
                   validate_template_vars
    Drift detection: DriftDetector, DriftReport
    Scaffolding: AdkScaffolder, ScaffoldResult
    Test harness: AdkTestHarness, HarnessResult
    Results: ImportResult, ExportResult, DeployResult
    Errors: AdkError, AdkParseError, AdkImportError, AdkExportError,
            AdkDeployError
"""
from __future__ import annotations

from adk.callbacks import CallbackRegistry, CallbackType, make_permission_callback
from adk.deployer import AdkDeployer
from adk.drift_detector import DriftDetector, DriftReport
from adk.errors import (
    AdkDeployError,
    AdkError,
    AdkExportError,
    AdkImportError,
    AdkParseError,
)
from adk.exporter import AdkExporter
from adk.importer import AdkImporter
from adk.mapper import AdkMapper
from adk.parser import parse_agent_directory
from adk.runtime import AdkExecutionResult, AdkRuntimeAdapter
from adk.scaffold import AdkScaffolder, ScaffoldResult
from adk.session import AdkSession, AdkSessionManager, SessionStatus
from adk.state import AdkStateManager, StateScope
from adk.streaming import AdkStreamHandler, StreamEvent
from adk.template_vars import (
    extract_template_vars,
    resolve_template_vars,
    validate_template_vars,
)
from adk.test_harness import AdkTestHarness, HarnessResult
from adk.vertex_engine import VertexEngineConfig, VertexEngineDeployer
from adk.memory_bank import MemoryBankConfig, MemoryBankAdapter
from adk.agent_garden import AgentGardenExporter
from adk.types import (
    AdkAgent,
    AdkAgentRef,
    AdkAgentTree,
    AdkAgentType,
    AdkCallbackSpec,
    AdkSessionConfig,
    AdkTemplateVar,
    AdkTool,
    AdkToolType,
    DeployResult,
    ExportResult,
    ImportResult,
)

__all__ = [
    # Parser
    "parse_agent_directory",
    # Mapper
    "AdkMapper",
    # Importer
    "AdkImporter",
    # Exporter
    "AdkExporter",
    # Deployer
    "AdkDeployer",
    # Runtime
    "AdkRuntimeAdapter",
    "AdkExecutionResult",
    # Callbacks
    "CallbackRegistry",
    "CallbackType",
    "make_permission_callback",
    # State
    "AdkStateManager",
    "StateScope",
    # Session
    "AdkSession",
    "AdkSessionManager",
    "SessionStatus",
    # Streaming
    "AdkStreamHandler",
    "StreamEvent",
    # Template vars
    "resolve_template_vars",
    "extract_template_vars",
    "validate_template_vars",
    # Drift detection
    "DriftDetector",
    "DriftReport",
    # Scaffolding
    "AdkScaffolder",
    "ScaffoldResult",
    # Test harness
    "AdkTestHarness",
    "HarnessResult",
    # Types
    "AdkAgent",
    "AdkAgentRef",
    "AdkAgentTree",
    "AdkAgentType",
    "AdkCallbackSpec",
    "AdkSessionConfig",
    "AdkTemplateVar",
    "AdkTool",
    "AdkToolType",
    "ImportResult",
    "ExportResult",
    "DeployResult",
    # Vertex Engine
    "VertexEngineConfig",
    "VertexEngineDeployer",
    # Memory Bank
    "MemoryBankConfig",
    "MemoryBankAdapter",
    # Agent Garden
    "AgentGardenExporter",
    # Errors
    "AdkError",
    "AdkParseError",
    "AdkImportError",
    "AdkExportError",
    "AdkDeployError",
]
