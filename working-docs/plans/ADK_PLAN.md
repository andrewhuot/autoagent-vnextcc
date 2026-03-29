# ADK Integration Implementation Plan

## Overview
Build ADK (Agent Development Kit) integration following the CX Agent Studio pattern. ADK agents are Python-based, requiring AST parsing instead of REST API calls.

## Architecture

```
adk/
├── __init__.py           # Public exports
├── types.py              # Pydantic models for ADK structures
├── parser.py             # AST-based Python source parser
├── mapper.py             # Bidirectional ADK ↔ AutoAgent mapping
├── importer.py           # Import ADK agent directory → config
├── exporter.py           # Export config → patched Python source
├── deployer.py           # Deploy to Cloud Run / Vertex AI
└── errors.py             # ADK-specific exceptions
```

## Key Differences from CX

| Aspect | CX Agent Studio | ADK |
|--------|----------------|-----|
| Source | REST API (JSON) | Python source files |
| Reading | HTTP GET requests | AST parsing |
| Writing | HTTP PATCH requests | Python file patches |
| Auth | GCP service account | GCP credentials for deploy only |
| Deploy | CX Environment API | Cloud Run / Vertex AI APIs |

## Implementation Tracks (Parallel)

### Track A: Types + Parser + Test Fixture
**Files**: `adk/types.py`, `adk/parser.py`, `tests/fixtures/sample_adk_agent/`, `tests/test_adk_parser.py`

**ADK Types**:
- `AdkAgentRef` - local directory reference
- `AdkAgent` - parsed Agent definition
- `AdkTool` - parsed tool function
- `AdkAgentTree` - hierarchical agent structure
- `ImportResult` - import operation result
- `ExportResult` - export operation result
- `DeployResult` - deployment result

**Parser Strategy**:
1. Find `__init__.py`, extract root_agent reference
2. Parse `agent.py` with AST - extract `Agent(...)` constructor
3. Parse `tools.py` - extract `@tool` decorated functions
4. Parse `prompts.py` - extract instruction strings
5. Parse `config.json` - extract generation settings
6. Recurse into `sub_agents/` directories
7. Return structured `AdkAgentTree`

**AST Patterns to Handle**:
- `Agent(name="...", instruction="...", ...)` - keyword args
- `@tool` decorator on functions with docstrings
- `sub_agents=[agent1, agent2]` - list of references
- Multi-line strings (triple-quoted)
- String concatenation
- f-strings (extract as templates)

**Test Fixture**: `tests/fixtures/sample_adk_agent/`
- Full agent with billing sub-agent
- 3-4 tools with docstrings
- Instruction prompts
- config.json

### Track B: Mapper + Importer
**Files**: `adk/mapper.py`, `adk/importer.py`, `tests/test_adk_mapper.py`, `tests/test_adk_importer.py`

**Mapping Rules (ADK → AutoAgent)**:
- `Agent.instruction` → `prompts.root` (or specialist name)
- `Agent.tools` docstrings → `tools.{tool_name}.description`
- `Agent.sub_agents` → `routing.rules` (derive keywords from sub-agent names)
- `Agent.generate_config` → generation settings (temperature, max_tokens, model)
- `Agent.model` → `model`
- Tool function bodies → stored as reference (read-only)
- Store original Python source for round-trip

**Importer Pipeline**:
1. Parse agent directory with `AdkParser`
2. Map to AutoAgent config with `AdkMapper`
3. Save config YAML
4. Save snapshot (original Python source files as zip or directory copy)
5. Return `ImportResult` with paths

### Track C: Exporter + Deployer
**Files**: `adk/exporter.py`, `adk/deployer.py`, `tests/test_adk_exporter.py`, `tests/test_adk_deployer.py`

**Mapping Rules (AutoAgent → ADK)**:
- `prompts.root` → `Agent.instruction` string
- `prompts.<specialist>` → sub-agent instructions
- `tools.{tool_name}.timeout_ms` → tool spec
- Generation settings → `Agent.generate_config`
- `model` → `Agent.model`

**Exporter Strategy** (CRITICAL - patch, don't rewrite):
1. Load original snapshot (Python source files)
2. Parse current state with AST
3. Diff optimized config against original
4. Generate AST patches for changed values
5. Apply patches preserving formatting, comments, imports
6. Write patched files to output directory

**Patch Types**:
- Instruction string replacement (preserve triple quotes)
- Tool docstring updates
- Generate_config value changes (temperature, max_tokens)
- Model name updates

**Deployer Strategy**:
1. Export to patched Python directory
2. Create deployment package (zip)
3. Deploy via:
   - **Cloud Run**: Cloud Run Admin API
   - **Vertex AI**: Vertex AI Agent Builder API
4. Return deployment URL + status

### Track D: CLI + API Routes
**Files**: `runner.py` (add commands), `api/routes/adk.py`, `tests/test_adk_api.py`

**CLI Commands** (add to runner.py):
```bash
autoagent adk import <path>                    # Import from local directory
autoagent adk export <path> [--output DIR]     # Export optimized config
autoagent adk deploy <path> [--target cloud-run|vertex-ai] [--project PROJECT] [--region REGION]
autoagent adk status <path>                    # Show agent structure
autoagent adk diff <path>                      # Preview export changes
```

**API Routes** (`api/routes/adk.py`):
```
POST   /api/adk/import         # Import from path
POST   /api/adk/export         # Export to path
POST   /api/adk/deploy         # Deploy to Cloud Run/Vertex AI
GET    /api/adk/status          # Agent structure summary
GET    /api/adk/diff            # Preview export diff
```

**Route Registration**: Update `api/server.py` to include ADK router

### Track E: Web Console
**Files**:
- `web/src/pages/AdkImport.tsx`
- `web/src/pages/AdkDeploy.tsx`
- `web/src/lib/types.ts` (add ADK types)
- `web/src/lib/api.ts` (add ADK hooks)
- `web/src/components/Sidebar.tsx` (add nav items)
- `web/src/App.tsx` (add routes)

**AdkImport.tsx**:
- Directory path input (with file browser)
- Preview parsed agent structure (tree view)
- Show agent name, tools, sub-agents
- Review config mapping preview
- Import button → call API → redirect to config editor

**AdkDeploy.tsx**:
- Select deployment target (Cloud Run / Vertex AI)
- GCP project + region inputs
- Preview changes (diff view)
- Deploy button with progress
- Show deployment URL on success

**TypeScript Types**:
```typescript
export interface AdkAgentRef { path: string }
export interface AdkAgent { name, model, instruction, tools, sub_agents, generate_config }
export interface AdkTool { name, description, function_body }
export interface AdkImportResult { config_path, snapshot_path, agent_name, surfaces_mapped }
export interface AdkExportResult { changes, output_path }
export interface AdkDeployResult { target, url, status }
```

**API Hooks**:
- `useAdkImport()`
- `useAdkExport()`
- `useAdkDeploy()`
- `useAdkStatus()`
- `useAdkDiff()`

## Integration Steps

1. Wire ADK routes into `api/server.py`
2. Add ADK pages to `web/src/App.tsx` routes
3. Add ADK nav items to `web/src/components/Sidebar.tsx`
4. Update `adk/__init__.py` with public exports
5. Add `adk` to Layer 1 in `tests/test_dependency_layers.py`
6. Create test fixture in `tests/fixtures/sample_adk_agent/`

## Quality Checkpoints

- [ ] `pytest tests/test_adk_parser.py -v` - Parser handles fixture correctly
- [ ] `pytest tests/test_adk_mapper.py -v` - Bidirectional mapping preserves data
- [ ] `pytest tests/test_adk_importer.py -v` - Import pipeline works end-to-end
- [ ] `pytest tests/test_adk_exporter.py -v` - Export preserves source formatting
- [ ] `pytest tests/test_adk_api.py -v` - API routes return correct shapes
- [ ] `pytest tests/test_dependency_layers.py -v` - Layer enforcement passes
- [ ] `cd web && npx tsc --noEmit` - TypeScript compiles
- [ ] Import → optimize → export round-trip preserves code structure

## Dispatch Strategy

Launch 5 parallel agents:
1. **Track A Agent** - Types, Parser, Test Fixture
2. **Track B Agent** - Mapper, Importer
3. **Track C Agent** - Exporter, Deployer
4. **Track D Agent** - CLI, API Routes
5. **Track E Agent** - Web Console

After all complete:
- Integration verification
- Full test suite run
- Commit + push
- Run openclaw event
