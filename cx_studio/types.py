"""Pydantic models for CX Studio and Dialogflow CX resources.

The current AgentLab integration needs to work with the real Dialogflow CX
resource hierarchy for agents, flows, intents, entity types, webhooks, pages,
and playbooks while still tolerating a few legacy CX Agent Studio code paths.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from portability.types import (
    ExportCapabilityMatrix,
    PortabilityReport,
    ProjectionQualityStatus,
)


class CxAgentRef(BaseModel):
    """Reference identifying a CX agent by project, location, and ID.

    `app_id` is optional and retained only for compatibility with older
    CX Agent Studio code paths that used `apps/.../agents/...`.
    """

    project: str
    location: str = "global"
    agent_id: str = ""
    app_id: str | None = None

    @property
    def parent(self) -> str:
        """Return the project/location parent resource path."""

        return f"projects/{self.project}/locations/{self.location}"

    @property
    def agent_parent(self) -> str:
        """Return the Dialogflow CX parent used for agent list/create calls."""

        return self.parent

    @property
    def app_name(self) -> str:
        """Return the optional legacy CX Agent Studio app path."""

        if self.app_id:
            return f"{self.parent}/apps/{self.app_id}"
        return self.parent

    @property
    def name(self) -> str:
        """Return the fully-qualified agent resource name."""

        if self.app_id:
            if not self.agent_id:
                return self.app_name
            return f"{self.app_name}/agents/{self.agent_id}"
        if self.agent_id:
            return f"{self.parent}/agents/{self.agent_id}"
        return self.parent


class CxAgent(BaseModel):
    """Dialogflow CX agent resource subset."""

    name: str = ""
    display_name: str = ""
    default_language_code: str = "en"
    description: str = ""
    time_zone: str = ""
    start_flow: str = ""
    start_playbook: str = ""
    generative_settings: dict[str, Any] = Field(default_factory=dict)
    speech_to_text_settings: dict[str, Any] = Field(default_factory=dict)
    text_to_speech_settings: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxPage(BaseModel):
    """Dialogflow CX page resource subset."""

    name: str = ""
    display_name: str = ""
    entry_fulfillment: dict[str, Any] = Field(default_factory=dict)
    form: dict[str, Any] = Field(default_factory=dict)
    transition_route_groups: list[str] = Field(default_factory=list)
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxFlow(BaseModel):
    """Dialogflow CX flow resource subset."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    transition_route_groups: list[str] = Field(default_factory=list)
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[CxPage] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxIntent(BaseModel):
    """Dialogflow CX intent resource subset."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    training_phrases: list[dict[str, Any]] = Field(default_factory=list)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxEntityType(BaseModel):
    """Dialogflow CX entity type resource subset."""

    name: str = ""
    display_name: str = ""
    kind: str = ""
    auto_expansion_mode: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    excluded_phrases: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxWebhook(BaseModel):
    """Dialogflow CX webhook resource subset."""

    name: str = ""
    display_name: str = ""
    generic_web_service: dict[str, Any] = Field(default_factory=dict)
    service_directory: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30
    disabled: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class CxTransitionRouteGroup(BaseModel):
    """Dialogflow CX transition route group resource subset."""

    name: str = ""
    display_name: str = ""
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxPlaybook(BaseModel):
    """Dialogflow CX playbook resource subset."""

    name: str = ""
    display_name: str = ""
    instruction: str = ""
    instructions: list[str] = Field(default_factory=list)
    goal: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    input_parameter_definitions: list[dict[str, Any]] = Field(default_factory=list)
    output_parameter_definitions: list[dict[str, Any]] = Field(default_factory=list)
    referenced_tools: list[str] = Field(default_factory=list)
    referenced_playbooks: list[str] = Field(default_factory=list)
    referenced_flows: list[str] = Field(default_factory=list)
    code_block: dict[str, Any] = Field(default_factory=dict)
    handlers: list[dict[str, Any]] = Field(default_factory=list)
    llm_model_settings: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def instruction_text(self) -> str:
        """Return the normalized instruction text for mapping and diffs."""

        if self.instruction:
            return self.instruction
        return "\n".join(step for step in self.instructions if step)


class CxTool(BaseModel):
    """CX tool resource subset."""

    name: str = ""
    display_name: str = ""
    tool_type: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxGenerator(BaseModel):
    """CX generator resource subset."""

    name: str = ""
    display_name: str = ""
    prompt_text: str = ""
    placeholders: list[dict[str, Any]] = Field(default_factory=list)
    llm_model_settings: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxProjectionMetadata(BaseModel):
    """Projection metadata for an editable CX-native structure."""

    quality: ProjectionQualityStatus = ProjectionQualityStatus.FAITHFUL
    source_platform: str = "cx_studio"
    source_refs: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class CxProjectionSummary(BaseModel):
    """Aggregate counts over projected CX-native editable records."""

    editable_surface_count: int = 0
    faithful_count: int = 0
    approximated_count: int = 0
    preserved_only_count: int = 0


class CxEditablePlaybook(BaseModel):
    """Editable CX-native playbook contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    goal: str = ""
    instructions: list[str] = Field(default_factory=list)
    input_parameters: list[dict[str, Any]] = Field(default_factory=list)
    output_parameters: list[dict[str, Any]] = Field(default_factory=list)
    handlers: list[dict[str, Any]] = Field(default_factory=list)
    referenced_tools: list[str] = Field(default_factory=list)
    referenced_playbooks: list[str] = Field(default_factory=list)
    referenced_flows: list[str] = Field(default_factory=list)
    code_block: dict[str, Any] = Field(default_factory=dict)
    llm_model_settings: dict[str, Any] = Field(default_factory=dict)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditablePage(BaseModel):
    """Editable CX-native page contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    entry_fulfillment: dict[str, Any] = Field(default_factory=dict)
    form: dict[str, Any] = Field(default_factory=dict)
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)
    route_group_ids: list[str] = Field(default_factory=list)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableFlow(BaseModel):
    """Editable CX-native flow contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    description: str = ""
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)
    route_group_ids: list[str] = Field(default_factory=list)
    pages: dict[str, CxEditablePage] = Field(default_factory=dict)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableTransitionRouteGroup(BaseModel):
    """Editable CX-native transition route group contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableIntent(BaseModel):
    """Editable CX-native intent contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    description: str = ""
    training_phrases: list[dict[str, Any]] = Field(default_factory=list)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableEntityType(BaseModel):
    """Editable CX-native entity-type contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    kind: str = ""
    auto_expansion_mode: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    excluded_phrases: list[str] = Field(default_factory=list)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableGenerator(BaseModel):
    """Editable CX-native generator contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    prompt_text: str = ""
    placeholders: list[dict[str, Any]] = Field(default_factory=list)
    llm_model_settings: dict[str, Any] = Field(default_factory=dict)
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableWebhook(BaseModel):
    """Editable CX-native webhook contract."""

    id: str
    resource_name: str = ""
    display_name: str = ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = 30000
    disabled: bool = False
    projection: CxProjectionMetadata = Field(default_factory=CxProjectionMetadata)


class CxEditableWorkspace(BaseModel):
    """Top-level editable CX-native contract stored in imported workspaces."""

    source_platform: str = "cx_studio"
    target_platform: str = "cx_agent_studio"
    projection_summary: CxProjectionSummary = Field(default_factory=CxProjectionSummary)
    playbooks: dict[str, CxEditablePlaybook] = Field(default_factory=dict)
    flows: dict[str, CxEditableFlow] = Field(default_factory=dict)
    transition_route_groups: dict[str, CxEditableTransitionRouteGroup] = Field(default_factory=dict)
    intents: dict[str, CxEditableIntent] = Field(default_factory=dict)
    entity_types: dict[str, CxEditableEntityType] = Field(default_factory=dict)
    generators: dict[str, CxEditableGenerator] = Field(default_factory=dict)
    webhooks: dict[str, CxEditableWebhook] = Field(default_factory=dict)
    preserved: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class CxTestCase(BaseModel):
    """Dialogflow CX test case subset."""

    name: str = ""
    display_name: str = ""
    tags: list[str] = Field(default_factory=list)
    conversation_turns: list[dict[str, Any]] = Field(default_factory=list)
    expected_output: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxEnvironment(BaseModel):
    """Dialogflow CX environment subset."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    version_configs: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxDataStore(BaseModel):
    """CX Studio datastore subset kept for compatibility."""

    name: str = ""
    display_name: str = ""
    data_store_type: str = "unstructured"
    content_entries: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxAgentSnapshot(BaseModel):
    """Complete point-in-time snapshot of a CX agent configuration."""

    agent: CxAgent = Field(default_factory=CxAgent)
    flows: list[CxFlow] = Field(default_factory=list)
    transition_route_groups: list[CxTransitionRouteGroup] = Field(default_factory=list)
    intents: list[CxIntent] = Field(default_factory=list)
    entity_types: list[CxEntityType] = Field(default_factory=list)
    webhooks: list[CxWebhook] = Field(default_factory=list)
    playbooks: list[CxPlaybook] = Field(default_factory=list)
    tools: list[CxTool] = Field(default_factory=list)
    generators: list[CxGenerator] = Field(default_factory=list)
    test_cases: list[CxTestCase] = Field(default_factory=list)
    environments: list[CxEnvironment] = Field(default_factory=list)
    data_stores: list[CxDataStore] = Field(default_factory=list)
    fetched_at: str = ""


class CxWidgetConfig(BaseModel):
    """Configuration required to render the web chat widget."""

    project_id: str
    agent_id: str
    location: str = "global"
    language_code: str = "en"
    chat_title: str = "Agent"
    primary_color: str = "#1a73e8"
    chat_icon: str = ""


class ImportResult(BaseModel):
    """Result of a successful CX-to-AgentLab import."""

    config_path: str
    eval_path: str | None = None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    test_cases_imported: int = 0
    workspace_path: str | None = None
    portability_report: PortabilityReport | None = None


class ExportResult(BaseModel):
    """Result of diffing or pushing AgentLab changes back to CX."""

    changes: list[dict[str, Any]] = Field(default_factory=list)
    pushed: bool = False
    resources_updated: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    export_matrix: ExportCapabilityMatrix | None = None


class DeployResult(BaseModel):
    """Result of deploying a CX agent to an environment."""

    environment: str
    status: str
    version_info: dict[str, Any] = Field(default_factory=dict)


class CxToolType(str, Enum):
    """Tool types supported by CX Studio surfaces."""

    OPENAPI = "OPEN_API"
    MCP = "MCP"
    PYTHON_CODE = "PYTHON_CODE"
    DATA_STORE = "DATA_STORE"
    CLIENT_FUNCTION = "CLIENT_FUNCTION"
    INTEGRATION_CONNECTOR = "INTEGRATION_CONNECTOR"
    WIDGET = "WIDGET"
    SYSTEM = "SYSTEM"


class CxDeploymentTarget(str, Enum):
    """Supported deployment targets for CX Agent Studio agents."""

    WEB_WIDGET = "web_widget"
    TELEPHONY_TWILIO = "telephony_twilio"
    TELEPHONY_GTP = "telephony_gtp"
    TELEPHONY_AUDIOCODES = "telephony_audiocodes"
    TELEPHONY_FIVE9 = "telephony_five9"
    CCAAS = "ccaas"
    API = "api"


class CxToolResource(BaseModel):
    """Typed CX tool definition for deployment helpers."""

    name: str = ""
    tool_type: CxToolType = CxToolType.OPENAPI
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class CxTransferRule(BaseModel):
    """CX transfer rule helper model."""

    source_agent: str
    target_agent: str
    condition: str = ""
    description: str = ""


class DeployPhase(str, Enum):
    """Phase in the CX deploy lifecycle."""

    PREFLIGHT = "preflight"
    CANARY = "canary"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ChangeSafety(str, Enum):
    """Safety classification for an individual export change."""

    SAFE = "safe"
    LOSSY = "lossy"
    BLOCKED = "blocked"


class PreflightResult(BaseModel):
    """Result of pre-deploy validation."""

    passed: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocked_surfaces: list[str] = Field(default_factory=list)
    safe_surfaces: list[str] = Field(default_factory=list)
    lossy_surfaces: list[str] = Field(default_factory=list)


class CanaryState(BaseModel):
    """Current canary deployment state for a CX agent."""

    phase: DeployPhase = DeployPhase.PREFLIGHT
    traffic_pct: int = 0
    deployed_version: str = ""
    previous_version: str = ""
    environment: str = ""
    promoted_at: str = ""
    rolled_back_at: str = ""
    deploy_metadata: dict[str, Any] = Field(default_factory=dict)


class CxDeployment(BaseModel):
    """Deployment configuration for a specific target channel."""

    target: CxDeploymentTarget
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
