"""Bidirectional conversions between AgentCardModel and other representations.

Supports:
- CanonicalAgent (shared/canonical_ir.py) ↔ AgentCardModel
- Config dict (agent/config/schema.py) ↔ AgentCardModel
- AdkAgentTree (adk/types.py) → AgentCardModel

Layer: Layer 1. May import from shared/, adk/ types only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
    EnvironmentConfig,
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

from .schema import (
    AgentCardModel,
    CallbackEntry,
    CallbackTiming,
    EnvironmentEntry,
    GuardrailEntry,
    HandoffEntry,
    McpServerEntry,
    PolicyEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)

if TYPE_CHECKING:
    from adk.types import AdkAgentTree


# ---------------------------------------------------------------------------
# CanonicalAgent → AgentCardModel
# ---------------------------------------------------------------------------


def from_canonical_agent(agent: CanonicalAgent) -> AgentCardModel:
    """Convert a CanonicalAgent to an AgentCardModel.

    Preserves all fields. Sub-agents are recursively converted.
    """
    return AgentCardModel(
        name=agent.name,
        description=agent.description,
        platform_origin=agent.platform_origin,
        instructions=agent.flatten_instructions(),
        tools=[_tool_contract_to_entry(t) for t in agent.tools],
        callbacks=[],  # CanonicalAgent doesn't store callbacks directly
        routing_rules=[_routing_spec_to_entry(r) for r in agent.routing_rules],
        guardrails=[_guardrail_spec_to_entry(g) for g in agent.guardrails],
        policies=[_policy_spec_to_entry(p) for p in agent.policies],
        handoffs=[_handoff_spec_to_entry(h) for h in agent.handoffs],
        mcp_servers=[_mcp_ref_to_entry(m) for m in agent.mcp_servers],
        environment=_env_config_to_entry(agent.environment),
        sub_agents=[_canonical_to_sub_agent(sa) for sa in agent.sub_agents],
        example_traces=list(agent.example_traces),
        metadata=dict(agent.metadata),
    )


def _canonical_to_sub_agent(agent: CanonicalAgent) -> SubAgentSection:
    """Convert a sub-CanonicalAgent to a SubAgentSection."""
    return SubAgentSection(
        name=agent.name,
        description=agent.description,
        instructions=agent.flatten_instructions(),
        tools=[_tool_contract_to_entry(t) for t in agent.tools],
        callbacks=[],
        routing_rules=[_routing_spec_to_entry(r) for r in agent.routing_rules],
        guardrails=[_guardrail_spec_to_entry(g) for g in agent.guardrails],
        policies=[_policy_spec_to_entry(p) for p in agent.policies],
        handoffs=[_handoff_spec_to_entry(h) for h in agent.handoffs],
        mcp_servers=[_mcp_ref_to_entry(m) for m in agent.mcp_servers],
        environment=_env_config_to_entry(agent.environment),
        sub_agents=[_canonical_to_sub_agent(sa) for sa in agent.sub_agents],
        metadata=dict(agent.metadata),
    )


# ---------------------------------------------------------------------------
# AgentCardModel → CanonicalAgent
# ---------------------------------------------------------------------------


def to_canonical_agent(card: AgentCardModel) -> CanonicalAgent:
    """Convert an AgentCardModel back to a CanonicalAgent.

    Instructions are stored as a single SYSTEM instruction block.
    Callbacks are stored in metadata since CanonicalAgent doesn't have
    a native callback field.
    """
    instructions: list[Instruction] = []
    if card.instructions:
        fmt = InstructionFormat.XML if card.instructions.strip().startswith("<") else InstructionFormat.TEXT
        instructions.append(Instruction(
            role=InstructionRole.SYSTEM,
            content=card.instructions,
            format=fmt,
            priority=100,
            label="root",
        ))

    metadata = dict(card.metadata)
    if card.callbacks:
        metadata["callbacks"] = [cb.model_dump() for cb in card.callbacks]

    return CanonicalAgent(
        name=card.name,
        description=card.description,
        platform_origin=card.platform_origin,
        instructions=instructions,
        tools=[_entry_to_tool_contract(t) for t in card.tools],
        routing_rules=[_entry_to_routing_spec(r) for r in card.routing_rules],
        policies=[_entry_to_policy_spec(p) for p in card.policies],
        guardrails=[_entry_to_guardrail_spec(g) for g in card.guardrails],
        handoffs=[_entry_to_handoff_spec(h) for h in card.handoffs],
        mcp_servers=[_entry_to_mcp_ref(m) for m in card.mcp_servers],
        environment=_entry_to_env_config(card.environment),
        sub_agents=[_sub_agent_to_canonical(sa) for sa in card.sub_agents],
        example_traces=list(card.example_traces),
        metadata=metadata,
    )


def _sub_agent_to_canonical(sa: SubAgentSection) -> CanonicalAgent:
    """Convert a SubAgentSection back to a CanonicalAgent."""
    instructions: list[Instruction] = []
    if sa.instructions:
        fmt = InstructionFormat.XML if sa.instructions.strip().startswith("<") else InstructionFormat.TEXT
        instructions.append(Instruction(
            role=InstructionRole.SYSTEM,
            content=sa.instructions,
            format=fmt,
            priority=100,
            label=sa.name,
        ))

    metadata = dict(sa.metadata)
    if sa.callbacks:
        metadata["callbacks"] = [cb.model_dump() for cb in sa.callbacks]

    return CanonicalAgent(
        name=sa.name,
        description=sa.description,
        instructions=instructions,
        tools=[_entry_to_tool_contract(t) for t in sa.tools],
        routing_rules=[_entry_to_routing_spec(r) for r in sa.routing_rules],
        guardrails=[_entry_to_guardrail_spec(g) for g in sa.guardrails],
        policies=[_entry_to_policy_spec(p) for p in sa.policies],
        handoffs=[_entry_to_handoff_spec(h) for h in sa.handoffs],
        mcp_servers=[_entry_to_mcp_ref(m) for m in sa.mcp_servers],
        environment=_entry_to_env_config(sa.environment),
        sub_agents=[_sub_agent_to_canonical(child) for child in sa.sub_agents],
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Config dict → AgentCardModel
# ---------------------------------------------------------------------------


def from_config_dict(config: dict[str, Any], name: str = "") -> AgentCardModel:
    """Convert a flat AgentLab config dict to an AgentCardModel.

    This handles the common config format with keys like:
    routing, prompts, tools, thresholds, guardrails, etc.
    """
    agent_name = name or config.get("name", config.get("agent_name", "agent"))

    # Instructions from prompts
    prompts = config.get("prompts", {})
    root_instruction = prompts.get("root", "")

    # Tools
    tools_config = config.get("tools", {})
    tools: list[ToolEntry] = []
    for tool_name, tool_cfg in tools_config.items():
        if isinstance(tool_cfg, dict):
            tools.append(ToolEntry(
                name=tool_name,
                description=tool_cfg.get("description", ""),
                timeout_ms=tool_cfg.get("timeout_ms"),
                metadata={k: v for k, v in tool_cfg.items()
                          if k not in ("description", "timeout_ms", "enabled")},
            ))
        elif isinstance(tool_cfg, bool) and tool_cfg:
            tools.append(ToolEntry(name=tool_name))

    # Routing rules
    routing = config.get("routing", {})
    rules_list = routing.get("rules", [])
    routing_rules: list[RoutingRuleEntry] = []
    for rule in rules_list:
        if isinstance(rule, dict):
            routing_rules.append(RoutingRuleEntry(
                target=rule.get("specialist", rule.get("target", "")),
                condition_type=rule.get("condition_type", "keyword"),
                keywords=rule.get("keywords", []),
                patterns=rule.get("patterns", []),
                priority=rule.get("priority", 0),
                fallback=rule.get("fallback", False),
            ))

    # Sub-agents from specialist prompts
    sub_agents: list[SubAgentSection] = []
    specialist_names = set()
    for rule in routing_rules:
        specialist_names.add(rule.target)

    for specialist in sorted(specialist_names):
        sa_instruction = prompts.get(specialist, "")
        sa = SubAgentSection(
            name=specialist,
            instructions=sa_instruction,
        )
        sub_agents.append(sa)

    # Guardrails
    guardrails_config = config.get("guardrails", [])
    guardrails: list[GuardrailEntry] = []
    if isinstance(guardrails_config, list):
        for g in guardrails_config:
            if isinstance(g, dict):
                guardrails.append(GuardrailEntry(
                    name=g.get("name", ""),
                    type=g.get("type", "both"),
                    enforcement=g.get("enforcement", "block"),
                    description=g.get("description", ""),
                ))

    # Environment
    env = EnvironmentEntry(
        model=config.get("model", ""),
        temperature=config.get("generation", {}).get("temperature") if isinstance(config.get("generation"), dict) else None,
        max_tokens=config.get("generation", {}).get("max_tokens") if isinstance(config.get("generation"), dict) else None,
    )

    # Policies
    policies_config = config.get("policies", [])
    policies: list[PolicyEntry] = []
    if isinstance(policies_config, list):
        for p in policies_config:
            if isinstance(p, dict):
                policies.append(PolicyEntry(
                    name=p.get("name", ""),
                    type=p.get("type", "behavioral"),
                    enforcement=p.get("enforcement", "recommended"),
                    description=p.get("description", ""),
                ))

    # Handoffs
    handoffs_config = config.get("handoffs", [])
    handoffs: list[HandoffEntry] = []
    if isinstance(handoffs_config, list):
        for h in handoffs_config:
            if isinstance(h, dict):
                handoffs.append(HandoffEntry(
                    source=h.get("source", ""),
                    target=h.get("target", ""),
                    context_transfer=h.get("context_transfer", "full"),
                    condition=h.get("condition", ""),
                ))

    return AgentCardModel(
        name=agent_name,
        description=config.get("description", ""),
        version=str(config.get("version", "1.0")),
        instructions=root_instruction,
        tools=tools,
        routing_rules=routing_rules,
        guardrails=guardrails,
        policies=policies,
        handoffs=handoffs,
        environment=env,
        sub_agents=sub_agents,
        metadata={k: v for k, v in config.items()
                  if k not in ("name", "agent_name", "description", "version",
                               "prompts", "tools", "routing", "guardrails",
                               "policies", "handoffs", "model", "generation")},
    )


# ---------------------------------------------------------------------------
# AgentCardModel → Config dict
# ---------------------------------------------------------------------------


def to_config_dict(card: AgentCardModel) -> dict[str, Any]:
    """Convert an AgentCardModel back to a flat AgentLab config dict."""
    config: dict[str, Any] = {}

    if card.name:
        config["name"] = card.name
    if card.description:
        config["description"] = card.description
    config["version"] = card.version

    # Prompts
    prompts: dict[str, str] = {}
    if card.instructions:
        prompts["root"] = card.instructions
    for sa in card.sub_agents:
        if sa.instructions:
            prompts[sa.name] = sa.instructions
    if prompts:
        config["prompts"] = prompts

    # Tools
    tools: dict[str, Any] = {}
    for tool in card.tools:
        tool_cfg: dict[str, Any] = {}
        if tool.description:
            tool_cfg["description"] = tool.description
        if tool.timeout_ms is not None:
            tool_cfg["timeout_ms"] = tool.timeout_ms
        tool_cfg.update(tool.metadata)
        tools[tool.name] = tool_cfg if tool_cfg else True
    # Include sub-agent tools
    for sa in card.sub_agents:
        for tool in sa.tools:
            tool_cfg = {}
            if tool.description:
                tool_cfg["description"] = tool.description
            if tool.timeout_ms is not None:
                tool_cfg["timeout_ms"] = tool.timeout_ms
            tools[tool.name] = tool_cfg if tool_cfg else True
    if tools:
        config["tools"] = tools

    # Routing
    if card.routing_rules:
        rules = []
        for r in card.routing_rules:
            rule: dict[str, Any] = {"specialist": r.target}
            if r.keywords:
                rule["keywords"] = r.keywords
            if r.patterns:
                rule["patterns"] = r.patterns
            if r.priority:
                rule["priority"] = r.priority
            if r.fallback:
                rule["fallback"] = True
            rules.append(rule)
        config["routing"] = {"rules": rules}

    # Guardrails
    if card.guardrails:
        config["guardrails"] = [
            {
                "name": g.name,
                "type": g.type,
                "enforcement": g.enforcement,
                "description": g.description,
            }
            for g in card.guardrails
        ]

    # Policies
    if card.policies:
        config["policies"] = [
            {
                "name": p.name,
                "type": p.type,
                "enforcement": p.enforcement,
                "description": p.description,
            }
            for p in card.policies
        ]

    # Handoffs
    if card.handoffs:
        config["handoffs"] = [
            {
                "source": h.source,
                "target": h.target,
                "context_transfer": h.context_transfer,
                "condition": h.condition,
            }
            for h in card.handoffs
        ]

    # Environment / generation
    if card.environment.model:
        config["model"] = card.environment.model
    gen: dict[str, Any] = {}
    if card.environment.temperature is not None:
        gen["temperature"] = card.environment.temperature
    if card.environment.max_tokens is not None:
        gen["max_tokens"] = card.environment.max_tokens
    if card.environment.top_p is not None:
        gen["top_p"] = card.environment.top_p
    if gen:
        config["generation"] = gen

    # Carry forward extra metadata
    config.update(card.metadata)

    return config


# ---------------------------------------------------------------------------
# AdkAgentTree → AgentCardModel
# ---------------------------------------------------------------------------


def from_adk_tree(tree: "AdkAgentTree") -> AgentCardModel:
    """Convert an AdkAgentTree to an AgentCardModel.

    Captures the full hierarchy including tools, callbacks, and sub-agents.
    """
    from adk.types import AdkAgentTree as _AdkTree

    agent = tree.agent

    # Tools
    tools = [
        ToolEntry(
            name=t.name,
            description=t.description,
            source_platform="google_adk",
            metadata={"function_body": t.function_body, "signature": t.signature}
            if t.function_body else {},
        )
        for t in tree.tools
    ]

    # Callbacks
    callbacks: list[CallbackEntry] = []
    for cb_spec in tree.callbacks:
        try:
            timing = CallbackTiming(cb_spec.callback_type)
        except ValueError:
            continue
        callbacks.append(CallbackEntry(
            name=cb_spec.name,
            timing=timing,
            description=cb_spec.description,
            function_name=cb_spec.function_name,
            signature=cb_spec.signature,
            body=cb_spec.function_body,
        ))

    # Also add callbacks referenced on the agent object itself
    _add_agent_callback_refs(agent, callbacks)

    # Environment
    env = EnvironmentEntry(
        model=agent.model,
        provider="google_adk",
    )
    gen_config = agent.generate_config or tree.config
    if gen_config:
        env.temperature = gen_config.get("temperature")
        env.max_tokens = gen_config.get("max_output_tokens", gen_config.get("max_tokens"))
        env.top_p = gen_config.get("top_p")
        env.top_k = gen_config.get("top_k")

    # Sub-agents (recursive)
    sub_agents = [_adk_tree_to_sub_agent(sa) for sa in tree.sub_agents]

    return AgentCardModel(
        name=agent.name,
        description=f"Google ADK agent: {agent.name}",
        platform_origin="google_adk",
        instructions=agent.instruction,
        tools=tools,
        callbacks=callbacks,
        environment=env,
        sub_agents=sub_agents,
        metadata={"source_path": str(tree.source_path)} if str(tree.source_path) != "." else {},
    )


def _adk_tree_to_sub_agent(tree: "AdkAgentTree") -> SubAgentSection:
    """Recursively convert an ADK sub-agent tree to a SubAgentSection."""
    agent = tree.agent

    tools = [
        ToolEntry(
            name=t.name,
            description=t.description,
            source_platform="google_adk",
            metadata={"function_body": t.function_body, "signature": t.signature}
            if t.function_body else {},
        )
        for t in tree.tools
    ]

    callbacks: list[CallbackEntry] = []
    for cb_spec in tree.callbacks:
        try:
            timing = CallbackTiming(cb_spec.callback_type)
        except ValueError:
            continue
        callbacks.append(CallbackEntry(
            name=cb_spec.name,
            timing=timing,
            description=cb_spec.description,
            function_name=cb_spec.function_name,
            signature=cb_spec.signature,
            body=cb_spec.function_body,
        ))
    _add_agent_callback_refs(agent, callbacks)

    env = EnvironmentEntry(model=agent.model, provider="google_adk")
    gen_config = agent.generate_config or tree.config
    if gen_config:
        env.temperature = gen_config.get("temperature")
        env.max_tokens = gen_config.get("max_output_tokens", gen_config.get("max_tokens"))

    return SubAgentSection(
        name=agent.name,
        agent_type=agent.agent_type.value if hasattr(agent.agent_type, "value") else str(agent.agent_type),
        instructions=agent.instruction,
        tools=tools,
        callbacks=callbacks,
        environment=env,
        sub_agents=[_adk_tree_to_sub_agent(sa) for sa in tree.sub_agents],
    )


def _add_agent_callback_refs(agent: Any, callbacks: list[CallbackEntry]) -> None:
    """Add callback entries from agent-level callback name references."""
    existing_names = {cb.name for cb in callbacks}
    cb_fields = [
        ("before_model_callback", CallbackTiming.BEFORE_MODEL),
        ("after_model_callback", CallbackTiming.AFTER_MODEL),
        ("before_agent_callback", CallbackTiming.BEFORE_AGENT),
        ("after_agent_callback", CallbackTiming.AFTER_AGENT),
        ("before_tool_callback", CallbackTiming.BEFORE_TOOL),
        ("after_tool_callback", CallbackTiming.AFTER_TOOL),
    ]
    for field, timing in cb_fields:
        name = getattr(agent, field, "")
        if name and name not in existing_names:
            callbacks.append(CallbackEntry(
                name=name,
                timing=timing,
                function_name=name,
            ))


# ---------------------------------------------------------------------------
# Type conversion helpers: CanonicalAgent types ↔ AgentCard types
# ---------------------------------------------------------------------------


def _tool_contract_to_entry(tc: ToolContract) -> ToolEntry:
    return ToolEntry(
        name=tc.name,
        description=tc.description,
        parameters=[
            {
                "name": p.name,
                "type": p.type,
                "description": p.description,
                "required": p.required,
                **({"default": p.default} if p.default is not None else {}),
                **({"enum": p.enum} if p.enum else {}),
            }
            for p in tc.parameters
        ],
        timeout_ms=tc.timeout_ms,
        invocation_hint=tc.invocation_hint.value,
        source_platform=tc.source_platform,
        metadata=dict(tc.metadata),
    )


def _entry_to_tool_contract(te: ToolEntry) -> ToolContract:
    params = [
        ToolParameter(
            name=p.get("name", ""),
            type=p.get("type", "string"),
            description=p.get("description", ""),
            required=p.get("required", False),
            default=p.get("default"),
            enum=p.get("enum"),
        )
        for p in te.parameters
    ]
    try:
        hint = ToolInvocationHint(te.invocation_hint)
    except ValueError:
        hint = ToolInvocationHint.AUTO
    return ToolContract(
        name=te.name,
        description=te.description,
        parameters=params,
        invocation_hint=hint,
        source_platform=te.source_platform,
        timeout_ms=te.timeout_ms,
        metadata=dict(te.metadata),
    )


def _routing_spec_to_entry(rs: RoutingRuleSpec) -> RoutingRuleEntry:
    return RoutingRuleEntry(
        target=rs.target,
        condition_type=rs.condition_type.value,
        keywords=list(rs.keywords),
        patterns=list(rs.patterns),
        priority=rs.priority,
        fallback=rs.fallback,
        metadata=dict(rs.metadata),
    )


def _entry_to_routing_spec(re_: RoutingRuleEntry) -> RoutingRuleSpec:
    try:
        ct = ConditionType(re_.condition_type)
    except ValueError:
        ct = ConditionType.KEYWORD
    return RoutingRuleSpec(
        target=re_.target,
        condition_type=ct,
        keywords=list(re_.keywords),
        patterns=list(re_.patterns),
        priority=re_.priority,
        fallback=re_.fallback,
        metadata=dict(re_.metadata),
    )


def _guardrail_spec_to_entry(gs: GuardrailSpec) -> GuardrailEntry:
    return GuardrailEntry(
        name=gs.name,
        type=gs.type.value,
        description=gs.description,
        enforcement=gs.enforcement.value,
        condition=gs.condition,
        metadata=dict(gs.metadata),
    )


def _entry_to_guardrail_spec(ge: GuardrailEntry) -> GuardrailSpec:
    try:
        gt = GuardrailType(ge.type)
    except ValueError:
        gt = GuardrailType.BOTH
    try:
        enf = GuardrailEnforcement(ge.enforcement)
    except ValueError:
        enf = GuardrailEnforcement.BLOCK
    return GuardrailSpec(
        name=ge.name,
        type=gt,
        description=ge.description,
        enforcement=enf,
        condition=ge.condition,
        metadata=dict(ge.metadata),
    )


def _policy_spec_to_entry(ps: PolicySpec) -> PolicyEntry:
    return PolicyEntry(
        name=ps.name,
        type=ps.type.value,
        description=ps.description,
        enforcement=ps.enforcement.value,
        metadata=dict(ps.metadata),
    )


def _entry_to_policy_spec(pe: PolicyEntry) -> PolicySpec:
    try:
        pt = PolicyType(pe.type)
    except ValueError:
        pt = PolicyType.BEHAVIORAL
    try:
        enf = PolicyEnforcement(pe.enforcement)
    except ValueError:
        enf = PolicyEnforcement.RECOMMENDED
    return PolicySpec(
        name=pe.name,
        type=pt,
        description=pe.description,
        enforcement=enf,
        metadata=dict(pe.metadata),
    )


def _handoff_spec_to_entry(hs: HandoffSpec) -> HandoffEntry:
    return HandoffEntry(
        source=hs.source,
        target=hs.target,
        condition=hs.condition,
        context_transfer=hs.context_transfer.value,
        metadata=dict(hs.metadata),
    )


def _entry_to_handoff_spec(he: HandoffEntry) -> HandoffSpec:
    try:
        ct = ContextTransfer(he.context_transfer)
    except ValueError:
        ct = ContextTransfer.FULL
    return HandoffSpec(
        source=he.source,
        target=he.target,
        condition=he.condition,
        context_transfer=ct,
        metadata=dict(he.metadata),
    )


def _mcp_ref_to_entry(mr: McpServerRef) -> McpServerEntry:
    return McpServerEntry(
        name=mr.name,
        config=dict(mr.config),
        tools_exposed=list(mr.tools_exposed),
        metadata=dict(mr.metadata),
    )


def _entry_to_mcp_ref(me: McpServerEntry) -> McpServerRef:
    return McpServerRef(
        name=me.name,
        config=dict(me.config),
        tools_exposed=list(me.tools_exposed),
        metadata=dict(me.metadata),
    )


def _env_config_to_entry(ec: EnvironmentConfig) -> EnvironmentEntry:
    return EnvironmentEntry(
        model=ec.model,
        provider=ec.provider,
        temperature=ec.temperature,
        max_tokens=ec.max_tokens,
        settings=dict(ec.settings),
    )


def _entry_to_env_config(ee: EnvironmentEntry) -> EnvironmentConfig:
    settings = dict(ee.settings)
    if ee.top_p is not None:
        settings["top_p"] = ee.top_p
    if ee.top_k is not None:
        settings["top_k"] = ee.top_k
    return EnvironmentConfig(
        model=ee.model,
        provider=ee.provider,
        temperature=ee.temperature,
        max_tokens=ee.max_tokens,
        settings=settings,
    )
