# Canonical IR & Adapter Normalization — Findings

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/canonical-ir-adapters-claude-opus`

## What Changed

### 1. Canonical IR types (`shared/canonical_ir.py`)

New Pydantic-based typed intermediate representation with 14 component types:

- **CanonicalAgent** — top-level node with recursive `sub_agents` for the
  component graph
- **Instruction** — typed instruction block with role (system/persona/task/
  constraint), format (text/xml/markdown), and priority ordering
- **ToolContract** — typed tool definition with `ToolParameter` list capturing
  name, type, description, required, default, and enum constraints
- **RoutingRuleSpec** — routing rule with condition type (keyword/pattern/
  intent/llm), keywords, patterns, and priority
- **GuardrailSpec** — safety/quality gate with type (input/output/both),
  enforcement (block/warn/log), and trigger conditions
- **PolicySpec** — behavioral constraint with type (behavioral/safety/
  compliance/operational) and enforcement level
- **HandoffSpec** — agent-to-agent transfer with source, target, condition,
  and context transfer mode
- **McpServerRef** — MCP server reference with config and tools exposed
- **EnvironmentConfig** — runtime settings (model, provider, temperature,
  max_tokens)
- **FidelityNote** — per-field conversion fidelity tracking (faithful/
  approximated/lossy/missing)

All types use `model_config = {"extra": "allow"}` for forward compatibility.

### 2. Conversion functions (`shared/canonical_ir_convert.py`)

Six conversion directions implemented:

| Direction | Function | Key behavior |
|---|---|---|
| ImportedAgentSpec → CanonicalAgent | `from_imported_spec()` | Upgrades untyped dicts to typed components; extracts tool parameters from `parameters`, `input_schema`, and `signature` formats |
| CanonicalAgent → config dict | `to_config_dict()` | Produces YAML-compatible dict; sub-agents flattened to routing rules + prompts |
| CanonicalAgent → ImportedAgentSpec | `to_imported_spec()` | Downgrade for legacy workspace creation path |
| config dict → CanonicalAgent | `from_config_dict()` | Handles both legacy `tools` and new `tools_config`; string guardrails upgraded to GuardrailSpec |
| AdkAgentTree → CanonicalAgent | `from_adk_tree()` | Recursive tree preserved; callbacks mapped as operational policies |
| AgentConfig ↔ CanonicalAgent | `.to_canonical()` / `.from_canonical()` | Bidirectional via `to_config_dict` / `from_config_dict` |

### 3. Enriched adapters

- **OpenAI Agents** (`adapters/openai_agents.py`): `@function_tool` decorated
  functions now have their parameters extracted from AST (name, type annotation,
  default values, required flag). New `_extract_function_parameters()` and
  `_annotation_to_str()` helpers.

- **Anthropic Claude** (`adapters/anthropic_claude.py`): Tool dicts with
  `input_schema` are now preserved through import. `@tool` decorated functions
  have parameters extracted via the same AST helper. Cross-adapter import from
  `openai_agents._extract_function_parameters`.

- **ImportedAgentSpec** (`adapters/base.py`): `build_config()` now emits
  `tools_config` (dynamic dict with parameters, input_schema, invocation_hint)
  instead of flat `{name: {enabled, description}}`. Guardrails emit full dicts
  with description/type/enforcement. Handoffs and MCP servers included in config.
  New `to_canonical()` method bridges to the typed IR.

### 4. Extended AgentConfig (`agent/config/schema.py`)

New fields on AgentConfig (all with backwards-compatible defaults):

- `tools_config: dict[str, Any]` — dynamic tool definitions alongside legacy
  `ToolsConfig`
- `guardrails: list[GuardrailConfig]` — typed guardrail entries
- `handoffs: list[HandoffConfig]` — agent-to-agent transfer definitions
- `policies: list[PolicyConfig]` — behavioral policy entries
- `mcp_servers: list[McpServerConfig]` — MCP server references
- `generation: GenerationConfig` — model temperature/max_tokens
- `adapter: dict[str, Any]` — adapter source metadata

PromptsConfig now accepts extra fields (`model_config = {"extra": "allow"}`)
for arbitrary specialist keys.

New methods: `to_canonical()` and `from_canonical()` for bidirectional conversion.

### 5. ADK mapper (`adk/mapper.py`)

New `to_canonical()` method on `AdkMapper` producing a CanonicalAgent with full
sub-agent hierarchy preservation, typed tool parameters from signatures, and
callbacks mapped as operational policies.

## What Fidelity Improved

| Component | Before | After |
|---|---|---|
| **Tool parameters** | Lost at import (just name+description) | Extracted from function signatures, input_schema, and parameter lists; survive round-trip through config |
| **Guardrails** | Just name strings | Typed with description, enforcement mode (block/warn/log), and scope (input/output/both) |
| **Handoffs** | Stored as flat `{target}` dicts | Typed with source, target, condition, and context transfer mode |
| **Instructions** | Single flat string in `prompts.root` | Typed with role, format detection (text/xml), priority ordering, and labeled blocks |
| **MCP servers** | In adapter_config only | First-class in config dict and AgentConfig |
| **ADK sub-agents** | Flattened to prompts+routing | Recursive CanonicalAgent graph; original hierarchy preserved |
| **Fidelity tracking** | None | Every conversion attaches FidelityNote per field with status and rationale |
| **Routing** | Derived from handoff names only | Typed with condition type (keyword/pattern/intent/llm), priority, fallback flag |

## What Remains Intentionally Lossy

| Component | Status | Rationale |
|---|---|---|
| Tool implementation bodies | In metadata only | Code is not config; stored as `_adk_function_body` for reference |
| CX page-level fulfillment | Preserved in CX snapshot, not in IR | Platform-specific execution logic |
| ADK callback function bodies | Referenced by name, body in metadata | Callbacks require code execution, not declarative config |
| Provider-specific runtime hooks | Not representable | Execution-time behavior, not agent definition |
| Starter evals | Not in IR | Eval-layer concern, not agent identity |
| Legacy ToolsConfig fields | Coexist with tools_config | Hardcoded catalog/orders_db/faq remain for existing code paths |

## Migration / Compatibility Risks

1. **`build_config()` output changed**: Now emits `tools_config` instead of
   `tools` for dynamic tool entries, and `guardrails` as dicts instead of
   string lists. Code that reads `spec.config["tools"]` expecting the old shape
   should check for `tools_config` first.

2. **AgentConfig new fields**: All default to empty, so existing YAML configs
   load without changes. `validate_config()` still works.

3. **PromptsConfig extra fields**: Now accepts arbitrary specialist keys. This
   is additive and doesn't break existing fixed-field access.

4. **Import order**: `_extract_function_parameters` is imported cross-adapter
   (anthropic imports from openai_agents). If module load order matters in some
   test configurations, this could surface. Verified in test suite.

5. **No breaking changes to API routes**: Config and connect routes still accept
   and return the same shapes. The new fields appear alongside existing ones.

## Test Results

- **63 new tests** in `tests/test_canonical_ir.py` — all passing
- **17 existing adapter/mapper tests** — all passing (no regressions)
- **13 config/connect/runtime tests** — all passing (no regressions)
- **3686 total tests passing** across the full suite
- **49 pre-existing failures** in workbench/harness/assistant tests (unrelated
  to this change; missing async deps in test environment)

## Files Changed

| File | Type | Lines |
|---|---|---|
| `shared/canonical_ir.py` | New | ~240 |
| `shared/canonical_ir_convert.py` | New | ~480 |
| `adapters/base.py` | Modified | +50 |
| `adapters/openai_agents.py` | Modified | +35 |
| `adapters/anthropic_claude.py` | Modified | +15 |
| `agent/config/schema.py` | Modified | +65 |
| `adk/mapper.py` | Modified | +15 |
| `tests/test_canonical_ir.py` | New | ~530 |
| `working-docs/canonical-ir-adapters-plan-claude-opus.md` | New | ~100 |
| `working-docs/canonical-ir-adapters-findings-claude-opus.md` | New | ~170 |
