"""Bidirectional conversions between CanonicalAgent and existing AgentLab types.

Each conversion function documents what is preserved and what is lossy.
Fidelity notes are attached to the resulting CanonicalAgent so callers
can inspect what was approximated.

Layer: Layer 0 (shared). May import from shared/ and adapters/base only.
"""

from __future__ import annotations

from typing import Any

from .canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
    EnvironmentConfig,
    FidelityNote,
    FidelityStatus,
    GuardrailEnforcement,
    GuardrailSpec,
    GuardrailType,
    HandoffSpec,
    Instruction,
    InstructionFormat,
    InstructionRole,
    McpServerRef,
    PolicyEnforcement,
    PolicySpec,
    PolicyType,
    RoutingRuleSpec,
    ToolContract,
    ToolInvocationHint,
    ToolParameter,
)


# ---------------------------------------------------------------------------
# ImportedAgentSpec → CanonicalAgent
# ---------------------------------------------------------------------------


def from_imported_spec(spec: Any) -> CanonicalAgent:
    """Convert an ImportedAgentSpec to a CanonicalAgent.

    Preserved: system_prompts, tools (name+description+parameters), guardrails,
    handoffs, mcp_refs, traces, metadata, platform.

    Approximated: tool parameter schemas (inferred from dict shape when present).
    Lost: adapter_config internals, starter_evals (eval-layer concern).
    """
    fidelity: list[FidelityNote] = []

    instructions = _convert_system_prompts(spec.system_prompts, fidelity)
    tools = _convert_tools(spec.tools, spec.platform, fidelity)
    guardrails = _convert_guardrails(spec.guardrails, fidelity)
    handoffs = _convert_handoffs(spec.handoffs, spec.agent_name, fidelity)
    mcp_servers = _convert_mcp_refs(spec.mcp_refs, fidelity)
    routing_rules = _infer_routing_from_handoffs(spec.handoffs, fidelity)
    environment = _infer_environment(spec.config, spec.metadata, fidelity)

    return CanonicalAgent(
        name=spec.agent_name,
        description=f"Imported from {spec.platform} via {spec.adapter} adapter",
        platform_origin=spec.platform,
        instructions=instructions,
        tools=tools,
        routing_rules=routing_rules,
        guardrails=guardrails,
        handoffs=handoffs,
        mcp_servers=mcp_servers,
        environment=environment,
        example_traces=list(spec.traces),
        metadata={
            "adapter": spec.adapter,
            "source": spec.source,
            "adapter_config": dict(spec.adapter_config),
            **dict(spec.metadata),
        },
        fidelity_notes=fidelity,
    )


def _convert_system_prompts(
    prompts: list[str],
    fidelity: list[FidelityNote],
) -> list[Instruction]:
    """Convert flat prompt strings to typed Instruction objects."""
    instructions: list[Instruction] = []
    for i, prompt in enumerate(prompts):
        role = InstructionRole.SYSTEM if i == 0 else InstructionRole.CONTEXT
        fmt = InstructionFormat.XML if prompt.strip().startswith("<") else InstructionFormat.TEXT
        instructions.append(Instruction(
            role=role,
            content=prompt,
            format=fmt,
            priority=100 - i,
            label=f"prompt_{i}" if i > 0 else "root",
        ))
    if prompts:
        fidelity.append(FidelityNote(
            field="instructions",
            status=FidelityStatus.FAITHFUL,
            rationale="System prompts mapped directly to typed instructions.",
        ))
    return instructions


def _convert_tools(
    tools: list[dict[str, Any]],
    platform: str,
    fidelity: list[FidelityNote],
) -> list[ToolContract]:
    """Convert untyped tool dicts to ToolContract objects."""
    contracts: list[ToolContract] = []
    has_params = False
    for tool in tools:
        name = str(tool.get("name", ""))
        if not name:
            continue
        parameters = _extract_tool_parameters(tool)
        if parameters:
            has_params = True

        invocation_hint = ToolInvocationHint.AUTO
        if tool.get("invocation_hint"):
            try:
                invocation_hint = ToolInvocationHint(tool["invocation_hint"])
            except ValueError:
                pass

        contracts.append(ToolContract(
            name=name,
            description=str(tool.get("description", "")),
            parameters=parameters,
            invocation_hint=invocation_hint,
            source_platform=platform,
            timeout_ms=tool.get("timeout_ms"),
            metadata={k: v for k, v in tool.items()
                      if k not in ("name", "description", "parameters",
                                   "input_schema", "invocation_hint", "timeout_ms")},
        ))

    if contracts:
        status = FidelityStatus.FAITHFUL if has_params else FidelityStatus.APPROXIMATED
        fidelity.append(FidelityNote(
            field="tools",
            status=status,
            rationale="Tool names and descriptions preserved; parameter schemas "
                      + ("extracted." if has_params else "not available from source."),
        ))
    return contracts


def _extract_tool_parameters(tool: dict[str, Any]) -> list[ToolParameter]:
    """Try to extract typed parameters from various tool dict shapes."""
    params: list[ToolParameter] = []

    if "parameters" in tool and isinstance(tool["parameters"], list):
        for p in tool["parameters"]:
            if isinstance(p, dict) and p.get("name"):
                params.append(ToolParameter(
                    name=str(p["name"]),
                    type=str(p.get("type", "string")),
                    description=str(p.get("description", "")),
                    required=bool(p.get("required", False)),
                    default=p.get("default"),
                    enum=p.get("enum"),
                ))

    if not params and "input_schema" in tool and isinstance(tool["input_schema"], dict):
        schema = tool["input_schema"]
        properties = schema.get("properties", {})
        required_names = set(schema.get("required", []))
        for prop_name, prop_def in properties.items():
            if isinstance(prop_def, dict):
                params.append(ToolParameter(
                    name=prop_name,
                    type=str(prop_def.get("type", "string")),
                    description=str(prop_def.get("description", "")),
                    required=prop_name in required_names,
                    default=prop_def.get("default"),
                    enum=prop_def.get("enum"),
                ))

    if not params and "signature" in tool:
        sig = str(tool["signature"])
        if "(" in sig and ")" in sig:
            args_str = sig[sig.index("(") + 1:sig.index(")")]
            for arg in args_str.split(","):
                arg = arg.strip()
                if not arg or arg == "self":
                    continue
                parts = arg.split(":")
                pname = parts[0].strip()
                ptype = parts[1].strip() if len(parts) > 1 else "string"
                if "=" in ptype:
                    ptype = ptype[:ptype.index("=")].strip()
                params.append(ToolParameter(
                    name=pname,
                    type=ptype,
                    required="=" not in arg,
                ))

    return params


def _convert_guardrails(
    guardrails: list[dict[str, Any]],
    fidelity: list[FidelityNote],
) -> list[GuardrailSpec]:
    """Convert untyped guardrail dicts to GuardrailSpec objects."""
    specs: list[GuardrailSpec] = []
    for g in guardrails:
        name = str(g.get("name", ""))
        if not name:
            continue

        gr_type = GuardrailType.BOTH
        if g.get("type"):
            try:
                gr_type = GuardrailType(g["type"])
            except ValueError:
                pass

        enforcement = GuardrailEnforcement.BLOCK
        if g.get("enforcement"):
            try:
                enforcement = GuardrailEnforcement(g["enforcement"])
            except ValueError:
                pass

        specs.append(GuardrailSpec(
            name=name,
            type=gr_type,
            description=str(g.get("description", "")),
            enforcement=enforcement,
            condition=str(g.get("condition", "")),
            metadata={k: v for k, v in g.items()
                      if k not in ("name", "type", "description", "enforcement", "condition")},
        ))

    if specs:
        has_descriptions = any(g.description for g in specs)
        fidelity.append(FidelityNote(
            field="guardrails",
            status=FidelityStatus.FAITHFUL if has_descriptions else FidelityStatus.APPROXIMATED,
            rationale="Guardrail names preserved; "
                      + ("descriptions available." if has_descriptions else "definitions not available from source."),
        ))
    return specs


def _convert_handoffs(
    handoffs: list[dict[str, Any]],
    agent_name: str,
    fidelity: list[FidelityNote],
) -> list[HandoffSpec]:
    """Convert untyped handoff dicts to HandoffSpec objects."""
    specs: list[HandoffSpec] = []
    for h in handoffs:
        target = str(h.get("target", ""))
        if not target:
            continue

        ctx = ContextTransfer.FULL
        if h.get("context_transfer"):
            try:
                ctx = ContextTransfer(h["context_transfer"])
            except ValueError:
                pass

        specs.append(HandoffSpec(
            source=str(h.get("source", agent_name)),
            target=target,
            condition=str(h.get("condition", "")),
            context_transfer=ctx,
            metadata={k: v for k, v in h.items()
                      if k not in ("source", "target", "condition", "context_transfer")},
        ))

    if specs:
        fidelity.append(FidelityNote(
            field="handoffs",
            status=FidelityStatus.FAITHFUL,
            rationale="Handoff source/target pairs preserved from adapter.",
        ))
    return specs


def _convert_mcp_refs(
    mcp_refs: list[dict[str, Any]],
    fidelity: list[FidelityNote],
) -> list[McpServerRef]:
    """Convert untyped MCP reference dicts to McpServerRef objects."""
    refs: list[McpServerRef] = []
    for ref in mcp_refs:
        name = str(ref.get("name", ""))
        if not name:
            continue
        refs.append(McpServerRef(
            name=name,
            config=dict(ref.get("config", {})),
            tools_exposed=list(ref.get("tools_exposed", [])),
            metadata={k: v for k, v in ref.items()
                      if k not in ("name", "config", "tools_exposed")},
        ))

    if refs:
        fidelity.append(FidelityNote(
            field="mcp_servers",
            status=FidelityStatus.FAITHFUL,
            rationale="MCP server references preserved.",
        ))
    return refs


def _infer_routing_from_handoffs(
    handoffs: list[dict[str, Any]],
    fidelity: list[FidelityNote],
) -> list[RoutingRuleSpec]:
    """Derive routing rules from handoff edges."""
    rules: list[RoutingRuleSpec] = []
    seen: set[str] = set()
    for h in handoffs:
        target = str(h.get("target", ""))
        if not target or target in seen:
            continue
        seen.add(target)

        keywords = _keywords_from_name(target)
        rules.append(RoutingRuleSpec(
            target=target,
            condition_type=ConditionType.KEYWORD,
            keywords=keywords,
        ))

    if rules:
        fidelity.append(FidelityNote(
            field="routing_rules",
            status=FidelityStatus.APPROXIMATED,
            rationale="Routing rules inferred from handoff targets; keywords derived from names.",
        ))
    return rules


def _infer_environment(
    config: dict[str, Any],
    metadata: dict[str, Any],
    fidelity: list[FidelityNote],
) -> EnvironmentConfig:
    """Extract environment config from imported spec config/metadata."""
    model = str(config.get("model", metadata.get("model", "")))
    provider = ""
    if "adapter" in config and isinstance(config["adapter"], dict):
        provider = str(config["adapter"].get("type", ""))

    env = EnvironmentConfig(model=model, provider=provider)

    generation = config.get("generation", {})
    if isinstance(generation, dict):
        if "temperature" in generation:
            env.temperature = float(generation["temperature"])
        if "max_tokens" in generation:
            env.max_tokens = int(generation["max_tokens"])

    if model:
        fidelity.append(FidelityNote(
            field="environment",
            status=FidelityStatus.FAITHFUL,
            rationale=f"Model '{model}' preserved from source config.",
        ))
    return env


def _keywords_from_name(name: str) -> list[str]:
    """Derive routing keywords from an agent/specialist name."""
    parts = name.lower().replace("-", "_").replace("_agent", "").replace("agent", "").split("_")
    return [p for p in parts if p and len(p) > 1]


# ---------------------------------------------------------------------------
# CanonicalAgent → config dict (for YAML serialization / AgentConfig)
# ---------------------------------------------------------------------------


def to_config_dict(agent: CanonicalAgent) -> dict[str, Any]:
    """Convert a CanonicalAgent to an AgentLab config dict.

    This produces the dict shape that can be written to v###.yaml and loaded
    by AgentConfig.model_validate(). Dynamic tools are placed in a
    'tools_config' key (dict[str, tool_entry]) alongside the legacy 'tools'
    section for backwards compatibility.

    Preserved: instructions→prompts, tools→tools_config, routing, guardrails,
    model, environment settings.
    Lost: fidelity_notes, sub_agent graph (flattened to routing+prompts),
    policy enforcement details, MCP server configs.
    """
    config: dict[str, Any] = {}

    # Prompts
    prompts: dict[str, str] = {}
    if agent.instructions:
        primary = agent.primary_instruction()
        if primary:
            prompts["root"] = primary
        for inst in agent.instructions:
            if inst.label and inst.label != "root" and inst.content != primary:
                prompts[inst.label] = inst.content
    for sa in agent.sub_agents:
        if sa.name and sa.instructions:
            prompts[sa.name] = sa.primary_instruction()
    if prompts:
        config["prompts"] = prompts

    # Tools
    tools_config: dict[str, Any] = {}
    for tool in agent.tools:
        entry: dict[str, Any] = {
            "enabled": True,
            "description": tool.description,
        }
        if tool.timeout_ms is not None:
            entry["timeout_ms"] = tool.timeout_ms
        if tool.parameters:
            entry["parameters"] = [p.model_dump(exclude_none=True) for p in tool.parameters]
        if tool.invocation_hint != ToolInvocationHint.AUTO:
            entry["invocation_hint"] = tool.invocation_hint.value
        if tool.metadata:
            entry.update(tool.metadata)
        tools_config[tool.name] = entry
    if tools_config:
        config["tools_config"] = tools_config

    # Routing
    routing_rules: list[dict[str, Any]] = []
    for rule in agent.routing_rules:
        routing_rules.append({
            "specialist": rule.target,
            "keywords": rule.keywords,
            "patterns": rule.patterns,
        })
    for sa in agent.sub_agents:
        if sa.name and not any(r["specialist"] == sa.name for r in routing_rules):
            routing_rules.append({
                "specialist": sa.name,
                "keywords": _keywords_from_name(sa.name),
                "patterns": [],
            })
    if routing_rules:
        config["routing"] = {"rules": routing_rules}

    # Guardrails
    if agent.guardrails:
        config["guardrails"] = [
            {"name": g.name, "type": g.type.value, "enforcement": g.enforcement.value,
             "description": g.description}
            for g in agent.guardrails
        ]

    # Policies
    if agent.policies:
        config["policies"] = [
            {"name": p.name, "type": p.type.value, "enforcement": p.enforcement.value,
             "description": p.description}
            for p in agent.policies
        ]

    # Handoffs
    if agent.handoffs:
        config["handoffs"] = [
            {"source": h.source, "target": h.target, "condition": h.condition,
             "context_transfer": h.context_transfer.value}
            for h in agent.handoffs
        ]

    # Environment / model
    if agent.environment.model:
        config["model"] = agent.environment.model
    if agent.environment.temperature is not None or agent.environment.max_tokens is not None:
        gen: dict[str, Any] = {}
        if agent.environment.temperature is not None:
            gen["temperature"] = agent.environment.temperature
        if agent.environment.max_tokens is not None:
            gen["max_tokens"] = agent.environment.max_tokens
        config["generation"] = gen

    # MCP servers
    if agent.mcp_servers:
        config["mcp_servers"] = [
            {"name": m.name, "config": m.config, "tools_exposed": m.tools_exposed}
            for m in agent.mcp_servers
        ]

    # Adapter metadata passthrough
    if agent.metadata.get("adapter"):
        config["adapter"] = {
            "type": agent.metadata["adapter"],
            "source": agent.metadata.get("source", ""),
        }

    return config


# ---------------------------------------------------------------------------
# CanonicalAgent → ImportedAgentSpec (downgrade for legacy compatibility)
# ---------------------------------------------------------------------------


def to_imported_spec(agent: CanonicalAgent) -> dict[str, Any]:
    """Convert a CanonicalAgent back to an ImportedAgentSpec-compatible dict.

    This enables round-tripping through the legacy workspace creation path.
    """
    system_prompts = [i.content for i in agent.instructions if i.content]
    tools = [
        {
            "name": t.name,
            "description": t.description,
            **({"parameters": [p.model_dump(exclude_none=True) for p in t.parameters]}
               if t.parameters else {}),
            **({"invocation_hint": t.invocation_hint.value}
               if t.invocation_hint != ToolInvocationHint.AUTO else {}),
            **t.metadata,
        }
        for t in agent.tools
    ]
    guardrails = [
        {"name": g.name, "description": g.description, "type": g.type.value,
         "enforcement": g.enforcement.value}
        for g in agent.guardrails
    ]
    handoffs = [
        {"source": h.source, "target": h.target, "condition": h.condition,
         "context_transfer": h.context_transfer.value}
        for h in agent.handoffs
    ]
    mcp_refs = [
        {"name": m.name, "config": m.config, "tools_exposed": m.tools_exposed}
        for m in agent.mcp_servers
    ]

    return {
        "adapter": agent.metadata.get("adapter", "canonical"),
        "source": agent.metadata.get("source", ""),
        "agent_name": agent.name,
        "platform": agent.platform_origin,
        "system_prompts": system_prompts,
        "tools": tools,
        "guardrails": guardrails,
        "handoffs": handoffs,
        "mcp_refs": mcp_refs,
        "session_patterns": [],
        "traces": agent.example_traces,
        "config": to_config_dict(agent),
        "metadata": agent.metadata,
    }


# ---------------------------------------------------------------------------
# config dict → CanonicalAgent (from persisted YAML)
# ---------------------------------------------------------------------------


def from_config_dict(
    config: dict[str, Any],
    *,
    name: str = "",
    platform: str = "",
) -> CanonicalAgent:
    """Reconstruct a CanonicalAgent from an AgentLab config dict.

    This handles both legacy configs (hardcoded tools) and new configs
    (dynamic tools_config dict).
    """
    fidelity: list[FidelityNote] = []

    # Instructions from prompts
    instructions: list[Instruction] = []
    prompts = config.get("prompts", {})
    if isinstance(prompts, dict):
        for key, value in prompts.items():
            if not isinstance(value, str) or not value:
                continue
            role = InstructionRole.SYSTEM if key == "root" else InstructionRole.CONTEXT
            priority = 100 if key == "root" else 50
            fmt = InstructionFormat.XML if value.strip().startswith("<") else InstructionFormat.TEXT
            instructions.append(Instruction(
                role=role, content=value, format=fmt, priority=priority, label=key,
            ))

    # Tools from tools_config (new) or tools (legacy)
    tools: list[ToolContract] = []
    tools_config = config.get("tools_config", {})
    if isinstance(tools_config, dict) and tools_config:
        for tname, tdef in tools_config.items():
            if not isinstance(tdef, dict):
                continue
            params = [
                ToolParameter(**p) for p in tdef.get("parameters", [])
                if isinstance(p, dict) and p.get("name")
            ]
            hint = ToolInvocationHint.AUTO
            if tdef.get("invocation_hint"):
                try:
                    hint = ToolInvocationHint(tdef["invocation_hint"])
                except ValueError:
                    pass
            tools.append(ToolContract(
                name=tname,
                description=str(tdef.get("description", "")),
                parameters=params,
                invocation_hint=hint,
                timeout_ms=tdef.get("timeout_ms"),
            ))
        fidelity.append(FidelityNote(
            field="tools", status=FidelityStatus.FAITHFUL,
            rationale="Tools loaded from tools_config with parameters.",
        ))
    else:
        legacy_tools = config.get("tools", {})
        if isinstance(legacy_tools, dict):
            for tname, tdef in legacy_tools.items():
                if not isinstance(tdef, dict):
                    continue
                tools.append(ToolContract(
                    name=tname,
                    description=str(tdef.get("description", "")),
                    timeout_ms=tdef.get("timeout_ms"),
                ))
            if tools:
                fidelity.append(FidelityNote(
                    field="tools", status=FidelityStatus.APPROXIMATED,
                    rationale="Tools loaded from legacy schema; no parameter info.",
                ))

    # Routing
    routing_rules: list[RoutingRuleSpec] = []
    routing = config.get("routing", {})
    if isinstance(routing, dict):
        for rule in routing.get("rules", []):
            if not isinstance(rule, dict):
                continue
            routing_rules.append(RoutingRuleSpec(
                target=str(rule.get("specialist", "")),
                keywords=list(rule.get("keywords", [])),
                patterns=list(rule.get("patterns", [])),
            ))

    # Guardrails
    guardrails: list[GuardrailSpec] = []
    for g in config.get("guardrails", []):
        if isinstance(g, dict) and g.get("name"):
            gr_type = GuardrailType.BOTH
            if g.get("type"):
                try:
                    gr_type = GuardrailType(g["type"])
                except ValueError:
                    pass
            enforcement = GuardrailEnforcement.BLOCK
            if g.get("enforcement"):
                try:
                    enforcement = GuardrailEnforcement(g["enforcement"])
                except ValueError:
                    pass
            guardrails.append(GuardrailSpec(
                name=str(g["name"]), type=gr_type, enforcement=enforcement,
                description=str(g.get("description", "")),
            ))
        elif isinstance(g, str):
            guardrails.append(GuardrailSpec(name=g))

    # Policies
    policies: list[PolicySpec] = []
    for p in config.get("policies", []):
        if isinstance(p, dict) and p.get("name"):
            policies.append(PolicySpec(
                name=str(p["name"]),
                type=PolicyType(p["type"]) if p.get("type") else PolicyType.BEHAVIORAL,
                enforcement=PolicyEnforcement(p["enforcement"]) if p.get("enforcement") else PolicyEnforcement.RECOMMENDED,
                description=str(p.get("description", "")),
            ))

    # Handoffs
    handoffs: list[HandoffSpec] = []
    for h in config.get("handoffs", []):
        if isinstance(h, dict) and h.get("target"):
            handoffs.append(HandoffSpec(
                source=str(h.get("source", name)),
                target=str(h["target"]),
                condition=str(h.get("condition", "")),
                context_transfer=ContextTransfer(h["context_transfer"]) if h.get("context_transfer") else ContextTransfer.FULL,
            ))

    # MCP servers
    mcp_servers: list[McpServerRef] = []
    for m in config.get("mcp_servers", []):
        if isinstance(m, dict) and m.get("name"):
            mcp_servers.append(McpServerRef(
                name=str(m["name"]),
                config=dict(m.get("config", {})),
                tools_exposed=list(m.get("tools_exposed", [])),
            ))

    # Environment
    model = str(config.get("model", ""))
    gen = config.get("generation", {})
    environment = EnvironmentConfig(
        model=model,
        temperature=gen.get("temperature") if isinstance(gen, dict) else None,
        max_tokens=gen.get("max_tokens") if isinstance(gen, dict) else None,
    )

    adapter = config.get("adapter", {})
    metadata: dict[str, Any] = {}
    if isinstance(adapter, dict):
        metadata["adapter"] = adapter.get("type", "")
        metadata["source"] = adapter.get("source", "")

    return CanonicalAgent(
        name=name,
        platform_origin=platform,
        instructions=instructions,
        tools=tools,
        routing_rules=routing_rules,
        policies=policies,
        guardrails=guardrails,
        handoffs=handoffs,
        mcp_servers=mcp_servers,
        environment=environment,
        metadata=metadata,
        fidelity_notes=fidelity,
    )


# ---------------------------------------------------------------------------
# AdkAgentTree → CanonicalAgent
# ---------------------------------------------------------------------------


def from_adk_tree(agent_tree: Any) -> CanonicalAgent:
    """Convert an AdkAgentTree to a CanonicalAgent.

    Preserved: instructions, tool names/descriptions/signatures, sub-agent
    hierarchy (recursive), model, generation settings, callback references.
    Approximated: routing (inferred from sub-agent names).
    Lost: tool function bodies (kept in metadata), callback function bodies.
    """
    fidelity: list[FidelityNote] = []
    agent = agent_tree.agent

    # Instructions
    instructions: list[Instruction] = []
    if agent.instruction:
        instructions.append(Instruction(
            role=InstructionRole.SYSTEM,
            content=agent.instruction,
            priority=100,
            label="root",
        ))
        fidelity.append(FidelityNote(
            field="instructions", status=FidelityStatus.FAITHFUL,
            rationale="ADK agent instruction mapped directly.",
        ))

    # Tools
    tools: list[ToolContract] = []
    for tool in agent_tree.tools:
        params = _extract_tool_parameters({
            "signature": tool.signature,
            "name": tool.name,
        })
        tools.append(ToolContract(
            name=tool.name,
            description=tool.description,
            parameters=params,
            source_platform="adk",
            metadata={
                "_adk_function_body": tool.function_body,
                "tool_type": tool.tool_type.value if hasattr(tool.tool_type, "value") else str(tool.tool_type),
            },
        ))
    if tools:
        fidelity.append(FidelityNote(
            field="tools", status=FidelityStatus.FAITHFUL,
            rationale="ADK tools mapped with descriptions and signatures; function bodies in metadata.",
        ))

    # Sub-agents (recursive)
    sub_agents: list[CanonicalAgent] = []
    routing_rules: list[RoutingRuleSpec] = []
    handoffs: list[HandoffSpec] = []
    for child_tree in agent_tree.sub_agents:
        child_canonical = from_adk_tree(child_tree)
        sub_agents.append(child_canonical)

        child_name = child_tree.agent.name or str(child_tree.source_path.name)
        routing_rules.append(RoutingRuleSpec(
            target=child_name,
            condition_type=ConditionType.KEYWORD,
            keywords=_keywords_from_name(child_name),
        ))
        handoffs.append(HandoffSpec(
            source=agent.name,
            target=child_name,
        ))

    if routing_rules:
        fidelity.append(FidelityNote(
            field="routing_rules", status=FidelityStatus.APPROXIMATED,
            rationale="Routing inferred from ADK sub-agent names.",
        ))

    # Environment
    model = agent.model or agent_tree.config.get("model", "")
    gen_config = agent.generate_config
    environment = EnvironmentConfig(
        model=model,
        provider="google" if "gemini" in model.lower() else "",
        temperature=gen_config.get("temperature"),
        max_tokens=gen_config.get("max_output_tokens") or gen_config.get("max_tokens"),
    )

    # Callbacks as policies
    policies: list[PolicySpec] = []
    for callback in agent_tree.callbacks:
        policies.append(PolicySpec(
            name=callback.function_name,
            type=PolicyType.OPERATIONAL,
            description=callback.description or f"ADK {callback.callback_type} callback",
            enforcement=PolicyEnforcement.REQUIRED,
            metadata={
                "callback_type": callback.callback_type,
                "_adk_function_body": callback.function_body,
            },
        ))
    if policies:
        fidelity.append(FidelityNote(
            field="policies", status=FidelityStatus.APPROXIMATED,
            rationale="ADK callbacks mapped as operational policies; behavior is approximated.",
        ))

    return CanonicalAgent(
        name=agent.name,
        platform_origin="adk",
        instructions=instructions,
        tools=tools,
        routing_rules=routing_rules,
        handoffs=handoffs,
        sub_agents=sub_agents,
        policies=policies,
        environment=environment,
        metadata={
            "adapter": "adk",
            "source": str(agent_tree.source_path),
            "agent_type": agent.agent_type.value if hasattr(agent.agent_type, "value") else str(agent.agent_type),
        },
        fidelity_notes=fidelity,
    )
