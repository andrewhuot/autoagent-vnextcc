"""Pydantic models for CX Agent Studio API resources.

These types represent the canonical shapes returned by and sent to the
CX Agent Studio REST API v1 (Google Cloud Customer Engagement AI).
They are intentionally separate from AutoAgent's internal config schema
so that the mapper layer can evolve each side independently.

API Reference: https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rest/v1-overview
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CxAgentRef(BaseModel):
    """Lightweight reference identifying a CX agent by its GCP coordinates.

    Note: CX Agent Studio uses a resource hierarchy with apps as a parent:
    projects/{project}/locations/{location}/apps/{app}/agents/{agent}
    """

    project: str
    location: str
    app_id: str  # The app that contains the agent
    agent_id: str = ""  # Optional - some operations work at app level

    @property
    def parent(self) -> str:
        """Return the parent resource path for list operations."""
        return f"projects/{self.project}/locations/{self.location}"

    @property
    def app_name(self) -> str:
        """Return the fully-qualified app resource name."""
        return f"projects/{self.project}/locations/{self.location}/apps/{self.app_id}"

    @property
    def name(self) -> str:
        """Return the fully-qualified agent resource name.

        If agent_id is not set, returns the app name instead (for app-level operations).
        """
        if self.agent_id:
            return f"projects/{self.project}/locations/{self.location}/apps/{self.app_id}/agents/{self.agent_id}"
        return self.app_name


class CxAgent(BaseModel):
    """CX Agent resource (subset of fields relevant to AutoAgent integration)."""

    name: str = ""
    display_name: str = ""
    default_language_code: str = "en"
    description: str = ""
    # generativeSettings is an open dict because the schema evolves frequently
    generative_settings: dict = Field(default_factory=dict)


class CxPlaybook(BaseModel):
    """CX Playbook resource — LLM-driven conversation logic."""

    name: str = ""
    display_name: str = ""
    instructions: list[str] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)


class CxTool(BaseModel):
    """CX Tool resource — OpenAPI, data store, function, or connector."""

    name: str = ""
    display_name: str = ""
    tool_type: str = ""
    spec: dict = Field(default_factory=dict)


class CxFlow(BaseModel):
    """CX Flow resource — deterministic conversation flow."""

    name: str = ""
    display_name: str = ""
    pages: list[dict] = Field(default_factory=list)
    transition_routes: list[dict] = Field(default_factory=list)
    event_handlers: list[dict] = Field(default_factory=list)


class CxIntent(BaseModel):
    """CX Intent resource with training phrases."""

    name: str = ""
    display_name: str = ""
    training_phrases: list[dict] = Field(default_factory=list)


class CxTestCase(BaseModel):
    """CX Test Case resource — maps to AutoAgent eval cases."""

    name: str = ""
    display_name: str = ""
    tags: list[str] = Field(default_factory=list)
    conversation_turns: list[dict] = Field(default_factory=list)
    expected_output: dict = Field(default_factory=dict)


class CxEnvironment(BaseModel):
    """CX Environment resource — draft, staging, or production."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    version_configs: list[dict] = Field(default_factory=list)


class CxDataStore(BaseModel):
    """CX Data Store resource — knowledge base, FAQ, procedure documentation."""

    name: str = ""
    display_name: str = ""
    data_store_type: str = "unstructured"  # unstructured, structured, website
    content_entries: list[dict] = Field(default_factory=list)


class CxAgentSnapshot(BaseModel):
    """Complete point-in-time snapshot of a CX agent's configuration.

    Assembles the results of all list API calls into a single object that
    can be persisted and used for offline import/mapping.
    """

    agent: CxAgent = Field(default_factory=CxAgent)
    playbooks: list[CxPlaybook] = Field(default_factory=list)
    tools: list[CxTool] = Field(default_factory=list)
    flows: list[CxFlow] = Field(default_factory=list)
    intents: list[CxIntent] = Field(default_factory=list)
    test_cases: list[CxTestCase] = Field(default_factory=list)
    environments: list[CxEnvironment] = Field(default_factory=list)
    data_stores: list[CxDataStore] = Field(default_factory=list)
    fetched_at: str = ""


class CxWidgetConfig(BaseModel):
    """Configuration required to render the chat-messenger web widget."""

    project_id: str
    agent_id: str
    location: str = "global"
    language_code: str = "en"
    chat_title: str = "Agent"
    primary_color: str = "#1a73e8"
    chat_icon: str = ""


class ImportResult(BaseModel):
    """Result of a successful CX-to-AutoAgent import operation."""

    config_path: str
    eval_path: Optional[str] = None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    test_cases_imported: int = 0


class ExportResult(BaseModel):
    """Result of pushing an optimized config back to CX Agent Studio."""

    changes: list[dict] = Field(default_factory=list)
    pushed: bool = False
    resources_updated: int = 0


class DeployResult(BaseModel):
    """Result of deploying a CX agent to an environment."""

    environment: str
    status: str
    version_info: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# New types for CX Agent Studio deployment parity (R1.11-R1.23)
# ---------------------------------------------------------------------------


class CxToolType(str, Enum):
    """Tool types supported by CX Agent Studio."""

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
    """CX Tool resource with typed tool_type and configuration.

    Extends the basic ``CxTool`` with a strongly-typed ``tool_type`` enum and
    a separate ``description`` field.  Use this model for creating new CX tools
    via the deployment pipeline.
    """

    name: str = ""
    tool_type: CxToolType = CxToolType.OPENAPI
    config: dict = Field(default_factory=dict)
    description: str = ""


class CxTransferRule(BaseModel):
    """CX transfer rule — routes conversation from one agent to another.

    Transfer rules are CX-only constructs that define explicit conditions
    under which a parent agent hands off to a child agent.
    """

    source_agent: str
    target_agent: str
    condition: str = ""
    description: str = ""


class CxDeployment(BaseModel):
    """CX deployment configuration for a specific target channel.

    Represents a deployment of a CX agent to a channel such as the web widget,
    telephony, CCaaS, or the REST API.
    """

    target: CxDeploymentTarget
    config: dict = Field(default_factory=dict)
    status: str = "draft"
