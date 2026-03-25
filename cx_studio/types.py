"""Pydantic models for CX Agent Studio API resources.

These types represent the canonical shapes returned by and sent to the
Dialogflow CX REST API (v3). They are intentionally separate from AutoAgent's
internal config schema so that the mapper layer can evolve each side
independently.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CxAgentRef(BaseModel):
    """Lightweight reference identifying a CX agent by its GCP coordinates."""

    project: str
    location: str
    agent_id: str

    @property
    def parent(self) -> str:
        """Return the parent resource path for list operations."""
        return f"projects/{self.project}/locations/{self.location}"

    @property
    def name(self) -> str:
        """Return the fully-qualified agent resource name."""
        return f"projects/{self.project}/locations/{self.location}/agents/{self.agent_id}"


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
    fetched_at: str = ""


class CxWidgetConfig(BaseModel):
    """Configuration required to render the df-messenger web widget."""

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
