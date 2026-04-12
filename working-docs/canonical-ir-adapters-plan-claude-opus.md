# Canonical IR & Adapter Normalization — Architecture Plan

**Author:** Claude Opus  
**Date:** 2026-04-12  
**Branch:** `feat/canonical-ir-adapters-claude-opus`

## Problem

AgentLab treats agents as flat config dicts and prompt strings. Every conversion
hop loses information:

1. **External format → ImportedAgentSpec**: Moderate fidelity but untyped — tools
   are `list[dict]` with inconsistent shapes across adapters.
2. **ImportedAgentSpec → v###.yaml**: `build_config()` drops guardrail definitions,
   handoff semantics, tool parameters, and MCP details.
3. **v###.yaml → AgentConfig**: `ToolsConfig` is hardcoded to three fields
   (`catalog`, `orders_db`, `faq`), no guardrails field, no handoffs.
4. **AgentConfig → CX/ADK export**: Routing simplified, policies absent.

There is no single typed representation that preserves meaningful agent behavior
across frameworks.

## Solution: Canonical Component Graph

A Pydantic-based typed intermediate representation (`CanonicalAgent`) that sits
at the center of all conversions. Platform-neutral, serializable, and rich enough
to preserve tool contracts, routing, guardrails, policies, handoffs, and subagent
relationships.

## Type Definitions

```
CanonicalAgent
├── name, description, platform_origin
├── instructions: list[Instruction]          # role, content, format, priority
├── tools: list[ToolContract]                # name, description, parameters[], invocation_hint
│   └── parameters: list[ToolParameter]      # name, type, description, required, default
├── routing_rules: list[RoutingRuleSpec]      # target, condition_type, keywords, patterns, priority
├── policies: list[PolicySpec]               # name, type, enforcement, description
├── guardrails: list[GuardrailSpec]          # name, type, trigger, enforcement, description
├── handoffs: list[HandoffSpec]              # source, target, condition, context_transfer
├── sub_agents: list[CanonicalAgent]         # recursive graph
├── mcp_servers: list[McpServerRef]          # name, config, tools_exposed
├── environment: EnvironmentConfig           # model, provider, temperature, max_tokens
├── example_traces: list[dict]               # preserved conversation examples
├── metadata: dict                           # adapter-specific passthrough
└── fidelity_notes: list[FidelityNote]       # field, status, rationale per conversion
```

## Conversion Strategy

### Directions implemented

| From → To | Method | Fidelity |
|---|---|---|
| ImportedAgentSpec → CanonicalAgent | `from_imported_spec()` | High — typed fields from untyped dicts |
| CanonicalAgent → config dict | `to_config_dict()` | Moderate — flattens to YAML-compatible |
| CanonicalAgent → ImportedAgentSpec | `to_imported_spec()` | Moderate — re-flattens typed fields |
| AgentConfig → CanonicalAgent | `from_agent_config()` | Low — AgentConfig is sparse |
| AdkAgentTree → CanonicalAgent | `from_adk_tree()` | High — tree structure preserved |
| CanonicalAgent → AgentConfig | `to_agent_config()` | Moderate — dynamic tools mapped |

### What's intentionally lossy

- **Tool implementation bodies**: Not part of the IR (code, not config).
- **CX page-level fulfillment logic**: Preserved in metadata, not modeled.
- **ADK callback function bodies**: Referenced by name, body in metadata.
- **Provider-specific runtime behavior**: Not representable in neutral IR.

## Integration Points

1. **adapters/base.py**: `ImportedAgentSpec.to_canonical()` and
   `CanonicalAgent.from_imported_spec()` bridge old and new.
2. **adk/mapper.py**: `AdkMapper.to_canonical()` for direct ADK→IR.
3. **agent/config/schema.py**: `AgentConfig` extended with dynamic `tools_config`
   dict and `guardrails` list for richer round-trips.
4. **Each adapter**: Enriched to produce typed tool parameters and guardrail
   definitions where the source provides them.

## Migration Path

1. **Phase 1 (this PR)**: Define IR types, add conversion functions, enrich
   adapters, extend AgentConfig. All existing code paths continue to work —
   canonical IR is additive, not replacing.
2. **Phase 2 (future)**: Workbench and builder operate on CanonicalAgent directly.
   Config versioning stores canonical form alongside YAML.
3. **Phase 3 (future)**: Export adapters consume CanonicalAgent instead of raw
   config dicts. CX/ADK export fidelity improves.

## Files Changed

| File | Change |
|---|---|
| `shared/canonical_ir.py` | New — IR type definitions |
| `shared/canonical_ir_convert.py` | New — conversion functions |
| `adapters/base.py` | Add `to_canonical()`, enrich `build_config()` |
| `adapters/openai_agents.py` | Extract tool parameters from AST |
| `adapters/anthropic_claude.py` | Extract tool input schemas |
| `adapters/transcript.py` | Minor enrichment |
| `agent/config/schema.py` | Add dynamic tools, guardrails, environment |
| `adk/mapper.py` | Add `to_canonical()` method |
| `tests/test_canonical_ir.py` | Comprehensive IR + conversion tests |

## Risks

- **Backwards compatibility**: All changes are additive. Existing serialized
  configs continue to load. AgentConfig new fields have defaults.
- **Schema evolution**: IR uses `model_config = {"extra": "allow"}` so unknown
  fields pass through rather than fail validation.
- **Performance**: IR construction is lightweight Pydantic instantiation — no I/O.
