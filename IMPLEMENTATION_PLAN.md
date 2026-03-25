# CX Agent Studio Integration — Implementation Plan

## Architecture Overview

```
cx_studio/                    # Layer 1 (advanced) — imports from core only
├── __init__.py               # Public API surface
├── auth.py                   # Google Cloud auth (ADC + service account JSON)
├── client.py                 # REST API client for CX Agent Studio v3
├── types.py                  # Pydantic models for CX API resources
├── mapper.py                 # Bidirectional mapping: CX schema ↔ AgentConfig
├── importer.py               # Import CX agent → AutoAgent config + evals
├── exporter.py               # Export AutoAgent config → CX Agent Studio
├── deployer.py               # Deploy to CX environments + widget HTML generation
└── errors.py                 # CX-specific error types

api/routes/cx_studio.py       # Layer 2 — FastAPI routes for web console
web/src/pages/CxImport.tsx    # Import wizard page
web/src/pages/CxDeploy.tsx    # Deploy + widget embed page
tests/test_cx_studio.py       # Comprehensive tests with mocked API responses
```

## Design Decisions

1. **Auth**: Support both ADC and service account JSON. ADC is default; `--credentials` flag for service account.
2. **Config mapping**: Map only optimizable surfaces (prompts, tools, routing, thresholds). Non-optimizable fields preserved as opaque passthrough in `_cx_metadata`.
3. **Deployment safety**: Export requires change card approval when in advanced/research mode.
4. **REST-only**: Use REST API directly (no MCP dependency). Simpler, more testable.
5. **Offline snapshots**: Import creates a complete local snapshot that works without GCP connectivity.
6. **Widget generation**: Both static HTML file export and live preview in web console.

## Module Details

### cx_studio/types.py — CX Resource Models

```python
from pydantic import BaseModel, Field

class CxAgentRef(BaseModel):
    """Reference to a CX agent (project/location/agent triple)."""
    project: str
    location: str = "global"
    agent_id: str

    @property
    def parent(self) -> str:
        return f"projects/{self.project}/locations/{self.location}"

    @property
    def name(self) -> str:
        return f"{self.parent}/agents/{self.agent_id}"

class CxAgent(BaseModel):
    """CX Agent resource."""
    name: str
    display_name: str
    default_language_code: str = "en"
    description: str = ""
    generative_settings: dict = Field(default_factory=dict)

class CxPlaybook(BaseModel):
    """CX Playbook resource."""
    name: str
    display_name: str
    instructions: list[str] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)

class CxTool(BaseModel):
    """CX Tool definition."""
    name: str
    display_name: str
    tool_type: str  # "OPEN_API" | "DATA_STORE" | "FUNCTION" | "CONNECTOR"
    spec: dict = Field(default_factory=dict)

class CxFlow(BaseModel):
    """CX Flow (conversation flow with pages and routes)."""
    name: str
    display_name: str
    pages: list[dict] = Field(default_factory=list)
    transition_routes: list[dict] = Field(default_factory=list)
    event_handlers: list[dict] = Field(default_factory=list)

class CxIntent(BaseModel):
    """CX Intent with training phrases."""
    name: str
    display_name: str
    training_phrases: list[dict] = Field(default_factory=list)

class CxTestCase(BaseModel):
    """CX Test Case — maps to AutoAgent eval case."""
    name: str
    display_name: str
    tags: list[str] = Field(default_factory=list)
    conversation_turns: list[dict] = Field(default_factory=list)
    expected_output: dict = Field(default_factory=dict)

class CxEnvironment(BaseModel):
    """CX Environment (draft, staging, production)."""
    name: str
    display_name: str
    description: str = ""
    version_configs: list[dict] = Field(default_factory=list)

class CxAgentSnapshot(BaseModel):
    """Complete snapshot of a CX agent for offline use."""
    agent: CxAgent
    playbooks: list[CxPlaybook] = Field(default_factory=list)
    tools: list[CxTool] = Field(default_factory=list)
    flows: list[CxFlow] = Field(default_factory=list)
    intents: list[CxIntent] = Field(default_factory=list)
    test_cases: list[CxTestCase] = Field(default_factory=list)
    environments: list[CxEnvironment] = Field(default_factory=list)
    fetched_at: str = ""  # ISO timestamp

class CxWidgetConfig(BaseModel):
    """Configuration for df-messenger web widget."""
    project_id: str
    agent_id: str
    location: str = "global"
    language_code: str = "en"
    chat_title: str = "Agent"
    primary_color: str = "#1a73e8"
    chat_icon: str = ""
```

### cx_studio/auth.py — Authentication

```python
class CxAuth:
    """Google Cloud authentication for CX API."""

    def __init__(self, credentials_path: str | None = None):
        """Initialize with ADC or explicit service account JSON."""

    def get_headers(self) -> dict[str, str]:
        """Return Authorization headers with fresh access token."""

    def _refresh_if_needed(self) -> None:
        """Refresh token if expired or about to expire."""
```

### cx_studio/client.py — REST API Client

```python
class CxClient:
    """REST client for Google Cloud CX Agent Studio API v3."""

    BASE_URL = "https://{region}-dialogflow.googleapis.com/v3"

    def __init__(self, auth: CxAuth, timeout: float = 30.0, max_retries: int = 3):
        ...

    # Agent operations
    def get_agent(self, ref: CxAgentRef) -> CxAgent: ...
    def list_agents(self, project: str, location: str) -> list[CxAgent]: ...
    def update_agent(self, ref: CxAgentRef, agent: CxAgent) -> CxAgent: ...

    # Playbook operations
    def list_playbooks(self, ref: CxAgentRef) -> list[CxPlaybook]: ...
    def update_playbook(self, ref: CxAgentRef, playbook: CxPlaybook) -> CxPlaybook: ...

    # Tool operations
    def list_tools(self, ref: CxAgentRef) -> list[CxTool]: ...

    # Flow operations
    def list_flows(self, ref: CxAgentRef) -> list[CxFlow]: ...

    # Intent operations
    def list_intents(self, ref: CxAgentRef) -> list[CxIntent]: ...

    # Test case operations
    def list_test_cases(self, ref: CxAgentRef) -> list[CxTestCase]: ...

    # Environment operations
    def list_environments(self, ref: CxAgentRef) -> list[CxEnvironment]: ...
    def deploy_to_environment(self, ref: CxAgentRef, env_name: str) -> dict: ...

    # Full snapshot
    def fetch_snapshot(self, ref: CxAgentRef) -> CxAgentSnapshot: ...
```

### cx_studio/mapper.py — Bidirectional Config Mapping

```python
class CxMapper:
    """Bidirectional mapping between CX agent snapshot and AgentConfig."""

    def to_autoagent(self, snapshot: CxAgentSnapshot) -> dict:
        """Convert CX snapshot → AutoAgent config dict.

        Mapping:
        - CxAgent.generative_settings → generation_settings
        - CxPlaybook.instructions → prompts (root + specialists)
        - CxTool definitions → tools config
        - CxFlow transition_routes → routing.rules
        - CxIntent training_phrases → routing keywords/patterns
        - CxTestCase → eval test cases (returned separately)
        - Non-mappable fields → _cx_metadata (opaque passthrough)
        """

    def to_cx(self, config: dict, base_snapshot: CxAgentSnapshot) -> CxAgentSnapshot:
        """Convert AutoAgent config → CX snapshot for export.

        Uses base_snapshot as template, overlays optimized fields.
        """

    def extract_test_cases(self, snapshot: CxAgentSnapshot) -> list[dict]:
        """Convert CX test cases → AutoAgent eval TestCase format."""
```

### cx_studio/importer.py — Import Pipeline

```python
class CxImporter:
    """Import a CX agent into AutoAgent."""

    def __init__(self, client: CxClient, mapper: CxMapper): ...

    def import_agent(
        self,
        ref: CxAgentRef,
        output_dir: str = ".",
        include_test_cases: bool = True,
        include_conversations: bool = False,
    ) -> ImportResult:
        """Full import pipeline:
        1. Fetch snapshot from CX API
        2. Map to AutoAgent config
        3. Extract test cases → eval suite
        4. Save snapshot for offline use
        5. Write config + eval files

        Returns ImportResult with paths and summary.
        """

class ImportResult(BaseModel):
    config_path: str
    eval_path: str | None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str]
    test_cases_imported: int
```

### cx_studio/exporter.py — Export Pipeline

```python
class CxExporter:
    """Export optimized AutoAgent config back to CX Agent Studio."""

    def __init__(self, client: CxClient, mapper: CxMapper): ...

    def export_agent(
        self,
        config: dict,
        ref: CxAgentRef,
        snapshot_path: str,
        dry_run: bool = False,
    ) -> ExportResult:
        """Export pipeline:
        1. Load base snapshot
        2. Map AutoAgent config → CX format
        3. Compute diff (for change card)
        4. If not dry_run, push changes via REST API

        Returns ExportResult with changes summary.
        """

    def preview_changes(self, config: dict, snapshot_path: str) -> list[dict]:
        """Preview what would change without pushing."""

class ExportResult(BaseModel):
    changes: list[dict]
    pushed: bool
    resources_updated: int
```

### cx_studio/deployer.py — Deployment + Widget

```python
class CxDeployer:
    """Deploy CX agent to environments and generate widget embed code."""

    def __init__(self, client: CxClient): ...

    def deploy_to_environment(
        self,
        ref: CxAgentRef,
        environment: str = "production",
    ) -> DeployResult: ...

    def generate_widget_html(
        self,
        widget_config: CxWidgetConfig,
        output_path: str | None = None,
    ) -> str:
        """Generate df-messenger widget HTML.
        Returns HTML string, optionally writes to file.
        """

    def get_deploy_status(self, ref: CxAgentRef) -> dict: ...

class DeployResult(BaseModel):
    environment: str
    status: str
    version_info: dict = Field(default_factory=dict)
```

### CLI Commands (runner.py cx subgroup)

```python
@cli.group("cx")
def cx_group() -> None:
    """Google Cloud CX Agent Studio — import, export, deploy."""

@cx_group.command("list")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--credentials", default=None)
def cx_list(project, location, credentials): ...

@cx_group.command("import")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--agent", "agent_id", required=True)
@click.option("--output-dir", default=".")
@click.option("--credentials", default=None)
@click.option("--include-test-cases/--no-test-cases", default=True)
def cx_import(project, location, agent_id, output_dir, credentials, include_test_cases): ...

@cx_group.command("export")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--agent", "agent_id", required=True)
@click.option("--config", "config_path", required=True)
@click.option("--snapshot", "snapshot_path", required=True)
@click.option("--credentials", default=None)
@click.option("--dry-run", is_flag=True)
def cx_export(project, location, agent_id, config_path, snapshot_path, credentials, dry_run): ...

@cx_group.command("deploy")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--agent", "agent_id", required=True)
@click.option("--environment", default="production")
@click.option("--credentials", default=None)
def cx_deploy(project, location, agent_id, environment, credentials): ...

@cx_group.command("widget")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--agent", "agent_id", required=True)
@click.option("--title", default="Agent")
@click.option("--color", default="#1a73e8")
@click.option("--output", "output_path", default=None)
def cx_widget(project, location, agent_id, title, color, output_path): ...

@cx_group.command("status")
@click.option("--project", required=True)
@click.option("--location", default="global")
@click.option("--agent", "agent_id", required=True)
@click.option("--credentials", default=None)
def cx_status(project, location, agent_id, credentials): ...
```

### API Routes (api/routes/cx_studio.py)

```
POST /api/cx/import     — Import a CX agent (returns task_id for async)
POST /api/cx/export     — Export config to CX (returns task_id)
POST /api/cx/deploy     — Deploy to CX environment
POST /api/cx/widget     — Generate widget HTML
GET  /api/cx/agents     — List agents in a project
GET  /api/cx/status     — Get CX agent status
GET  /api/cx/preview    — Preview export changes
```

### Web Pages

**CxImport.tsx** — Import wizard:
- Step 1: Enter project/location/credentials
- Step 2: Select agent from list
- Step 3: Preview mapped surfaces
- Step 4: Confirm and import

**CxDeploy.tsx** — Deploy + widget:
- Deploy section: Select environment, deploy with status
- Widget section: Configure and preview df-messenger embed, copy HTML

### Dependency Layer Classification

`cx_studio` → Layer 1 (LAYER_1_PREFIXES in test_dependency_layers.py)

It imports from:
- `agent.config.schema` (Layer 0) — AgentConfig for mapping
- `evals.runner` (Layer 0) — TestCase for eval import
- stdlib/PyPI only (pydantic, httpx)

It does NOT import from Layer 2 (api/, web/).

## Test Strategy

`tests/test_cx_studio.py`:
- Unit tests for mapper (round-trip: CX → AutoAgent → CX)
- Unit tests for auth (token refresh, error handling)
- Unit tests for client (mocked HTTP responses)
- Unit tests for importer/exporter (full pipeline with mocked client)
- Unit tests for deployer (widget HTML generation)
- Integration test for CLI commands (click.testing.CliRunner)
- Dependency layer test passes with cx_studio as Layer 1
