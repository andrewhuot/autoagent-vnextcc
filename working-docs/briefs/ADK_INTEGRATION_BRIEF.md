# ADK (Agent Development Kit) Integration Brief

## Mission
Build a bidirectional integration between AutoAgent and Google Agent Development Kit (ADK), mirroring the CX Agent Studio integration. Users should import ADK agents, optimize them, and export back — same UX pattern as `autoagent cx`.

## What is ADK?
Google's Agent Development Kit is a Python framework for building AI agents. Key characteristics:
- Agents defined in Python code (not YAML/JSON like CX)
- `agent.py` files with class-based agent definitions
- `__init__.py` exports the root agent
- Config via `agent.json` or inline Python
- Tools defined as Python functions with docstrings
- Sub-agents compose via `sub_agents` list
- Callbacks for pre/post processing
- Session state management
- Deployment via `adk deploy` to Cloud Run or Vertex AI

### ADK Agent Structure
```
my_agent/
├── __init__.py          # Exports root_agent
├── agent.py             # Agent class definition
├── tools.py             # Tool function definitions  
├── prompts.py           # System instructions / prompts
├── config.json          # Runtime config (model, temperature, etc.)
├── sub_agents/          # Sub-agent directories
│   ├── billing/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   └── tools.py
│   └── support/
│       ├── __init__.py
│       ├── agent.py
│       └── tools.py
└── tests/               # Agent tests
```

### ADK Agent Definition (Python)
```python
from google.adk.agents import Agent
from google.adk.tools import tool

root_agent = Agent(
    model="gemini-2.0-flash",
    name="support_agent",
    instruction="You are a helpful support agent...",
    tools=[lookup_order, search_kb, create_ticket],
    sub_agents=[billing_agent, tech_support_agent],
    before_model_callback=safety_check,
    generate_config={"temperature": 0.3, "max_output_tokens": 1024},
)
```

## Architecture — Mirror CX Pattern

```
adk/
├── __init__.py
├── parser.py            # Parse ADK Python source → structured config
├── types.py             # ADK-specific type definitions
├── mapper.py            # Bidirectional mapping: ADK ↔ AutoAgent schema
├── importer.py          # Import ADK agent directory → AutoAgent config
├── exporter.py          # Export optimized config → ADK Python source
├── deployer.py          # Deploy via adk CLI or Cloud Run API
└── errors.py            # ADK-specific errors
```

## Key Design Challenge: Python Source ↔ Config

Unlike CX (JSON REST API), ADK agents are defined in Python source code. The integration needs to:

### Import (Python → Config)
1. **Parse** the agent directory using AST to extract:
   - Agent name, model, instruction text
   - Tool function names and docstrings
   - Sub-agent hierarchy
   - Generate config (temperature, max tokens, etc.)
   - Before/after callbacks (just names, not implementation)
2. **Map** extracted data to AutoAgent config surfaces:
   - `instruction` → `instructions` surface
   - `tools` docstrings → `tool_descriptions` surface
   - `sub_agents` routing → `routing` surface
   - `generate_config` → `generation_settings` surface
   - Tool function bodies → `tool_implementations` (read-only reference)
3. **Store** the original source files as a snapshot for diffing later

### Export (Config → Python)
1. **Diff** the optimized config against the imported snapshot
2. **Generate patches** for the Python source:
   - Updated instruction strings
   - Modified tool docstrings
   - Adjusted generate_config values
   - New/modified routing rules
3. **Apply patches** to the original Python files (preserve formatting, comments)
4. **Write** the patched files to an output directory

The exporter should NEVER rewrite Python from scratch — always patch the original source to preserve developer's code style, comments, and custom logic.

## CLI Commands — Same Pattern as CX

```
autoagent adk import <path>                  # Import from local ADK agent directory
autoagent adk export <path> [--output DIR]   # Export optimized config back to ADK source
autoagent adk deploy <path> [--target cloud-run|vertex-ai] [--project PROJECT] [--region REGION]
autoagent adk status <path>                  # Show agent structure and config summary
autoagent adk diff <path>                    # Show what would change on export
```

## Config Mapping

| ADK Source | AutoAgent Surface |
|---|---|
| `Agent.instruction` | `instructions.{agent_name}` |
| `Agent.tools` (docstrings) | `tool_descriptions.{tool_name}` |
| `Agent.sub_agents` routing | `routing.rules` |
| `Agent.generate_config` | `generation_settings` |
| `Agent.model` | `generation_settings.model` |
| `Agent.before_model_callback` | `safety` (reference only) |
| Tool function bodies | `tool_implementations` (read-only) |
| Test files | Eval cases |

## API Endpoints

```
POST   /api/adk/import         # Import from path (body: { path: "..." })
POST   /api/adk/export         # Export to path (body: { path: "...", output: "..." })
POST   /api/adk/deploy         # Deploy (body: { path, target, project, region })
GET    /api/adk/status          # Agent structure summary (query: ?path=...)
GET    /api/adk/diff            # Preview export diff (query: ?path=...)
```

## Web Console

### `AdkImport.tsx` — Import Wizard
Similar to CxImport but for local directories:
1. Enter/browse agent directory path
2. Preview parsed agent structure (tree view of agents, tools, sub-agents)
3. Review config mapping (what surfaces will be created)
4. Confirm import

### `AdkDeploy.tsx` — Deploy Page  
1. Select deployment target (Cloud Run / Vertex AI)
2. Enter GCP project and region
3. Preview changes (diff view)
4. Deploy button with progress indicator

## ADK Python Parser (`adk/parser.py`)

Use Python's `ast` module to parse agent source files:

```python
def parse_agent_directory(path: Path) -> AdkAgentTree:
    """Parse an ADK agent directory into a structured representation."""
    # 1. Find __init__.py, look for root_agent export
    # 2. Parse agent.py — extract Agent() constructor args
    # 3. Parse tools.py — extract @tool decorated functions with docstrings
    # 4. Recurse into sub_agents/ directories
    # 5. Parse config.json if present
    # Return structured AdkAgentTree
```

Key AST patterns to handle:
- `Agent(name="...", instruction="...", ...)` — keyword args in constructor
- `@tool` decorator on functions
- `sub_agents=[agent1, agent2]` — list of references
- Multi-line instruction strings (triple-quoted)
- String concatenation in instructions
- f-strings in instructions (extract as templates)

## Implementation Tracks

**Track A — Types + Parser**: `adk/types.py`, `adk/parser.py`, `tests/test_adk_parser.py`
**Track B — Mapper + Importer**: `adk/mapper.py`, `adk/importer.py`, `tests/test_adk_importer.py`  
**Track C — Exporter + Deployer**: `adk/exporter.py`, `adk/deployer.py`, `tests/test_adk_exporter.py`
**Track D — CLI + API**: CLI commands in runner.py, `api/routes/adk.py`, `tests/test_adk_api.py`
**Track E — Web Console**: `web/src/pages/AdkImport.tsx`, `web/src/pages/AdkDeploy.tsx`, types/api hooks

## Test Fixtures

Create `tests/fixtures/sample_adk_agent/` with a realistic sample agent:
```
tests/fixtures/sample_adk_agent/
├── __init__.py          # from .agent import root_agent
├── agent.py             # Full Agent definition with sub_agents
├── tools.py             # 3-4 tool functions with docstrings
├── prompts.py           # Instruction strings
├── config.json          # { "model": "gemini-2.0-flash", "temperature": 0.3 }
└── sub_agents/
    └── billing/
        ├── __init__.py
        ├── agent.py
        └── tools.py
```

## Quality Bar
- `python3 -m pytest tests/ -x -q` — must pass with more tests than current
- `cd web && npx tsc --noEmit` — must pass  
- `python3 -m pytest tests/test_dependency_layers.py -v` — must pass (adk/ is Layer 1)
- Parser must handle the sample fixture correctly
- Import → export round-trip must preserve original source structure

## When Done
Commit: `feat: ADK integration — import, export, deploy for Agent Development Kit agents`
Push to master.
Run: `openclaw system event --text "Done: ADK integration — Python AST parser, import/export, deploy to Cloud Run/Vertex AI" --mode now`
