"""Pydantic models for CX Studio and Dialogflow CX resources.

The current AutoAgent integration needs to work with the real Dialogflow CX
resource hierarchy for agents, flows, intents, entity types, webhooks, pages,
and playbooks while still tolerating a few legacy CX Agent Studio code paths.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    transition_routes: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CxFlow(BaseModel):
    """Dialogflow CX flow resource subset."""

    name: str = ""
    display_name: str = ""
    description: str = ""
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


class CxPlaybook(BaseModel):
    """Dialogflow CX playbook resource subset."""

    name: str = ""
    display_name: str = ""
    instruction: str = ""
    instructions: list[str] = Field(default_factory=list)
    goal: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
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
    intents: list[CxIntent] = Field(default_factory=list)
    entity_types: list[CxEntityType] = Field(default_factory=list)
    webhooks: list[CxWebhook] = Field(default_factory=list)
    playbooks: list[CxPlaybook] = Field(default_factory=list)
    tools: list[CxTool] = Field(default_factory=list)
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
    """Result of a successful CX-to-AutoAgent import."""

    config_path: str
    eval_path: str | None = None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    test_cases_imported: int = 0
    workspace_path: str | None = None


class ExportResult(BaseModel):
    """Result of diffing or pushing AutoAgent changes back to CX."""

    changes: list[dict[str, Any]] = Field(default_factory=list)
    pushed: bool = False
    resources_updated: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


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


class CxDeployment(BaseModel):
    """Deployment configuration for a specific target channel."""

    target: CxDeploymentTarget
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
