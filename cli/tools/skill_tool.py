"""SkillTool — LLM-invokable skill execution.

Slash users can already run skills via ``/skill``; this tool extends that
to the model. When the LLM calls ``SkillTool(slug, arguments)`` we:

1. Resolve the skill in the active :class:`SkillRegistry`.
2. Apply the skill's ``allowed_tools`` via :func:`scoped_allowlist` so
   any tool calls made *during* the skill's nested turn are restricted
   to the declared surface.
3. Run a nested :class:`LLMOrchestrator.run_turn` with the skill's
   expanded prompt as the user input. Return the assistant text as the
   tool result so the outer turn can quote or summarise.

Recursion guard: skills that invoke skills are legal but capped. Each
invocation increments ``ToolContext.extra['skill_recursion_depth']``;
hitting :data:`MAX_SKILL_RECURSION` returns a failure so a misbehaving
chain doesn't spin forever.

Why a separate tool instead of just slash dispatch: the model often
needs to chain a well-defined procedure ("run the commit skill, then
decide the follow-up") and inventing ad-hoc prompts for it wastes
tokens. SkillTool gives the model a first-class way to reuse authored
procedures with their tool restrictions intact.
"""

from __future__ import annotations

from typing import Any, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


MAX_SKILL_RECURSION = 3
"""Cap on nested skill invocations in a single outer turn. Chosen
empirically — agents that need deeper chains should either flatten the
calls or pass through an :class:`AgentSpawn` subagent with its own
recursion budget."""

SKILL_RECURSION_KEY = "skill_recursion_depth"
""":class:`ToolContext.extra` key used to track nesting depth."""

SKILL_REGISTRY_KEY = "skill_registry"
"""Key under which the REPL publishes the active
:class:`~cli.user_skills.registry.SkillRegistry`. The orchestrator
threads the registry into every tool context so SkillTool can resolve
slugs without a module-level singleton."""

ORCHESTRATOR_FACTORY_KEY = "nested_orchestrator_factory"
"""Optional key. When present the factory produces a fresh
:class:`LLMOrchestrator` for the nested turn; without it SkillTool
returns the expanded prompt so the outer model can continue manually.
This lets agentlab environments without a live LLM (e.g. headless
tests, ``agentlab print`` with no API key) still exercise the tool
boundary."""


class SkillTool(Tool):
    """Execute a user skill and return the assistant output.

    Input: ``slug`` — required skill identifier; ``arguments`` —
    optional free-form string substituted into the skill's
    ``$ARGUMENTS`` placeholder or appended after the body.

    The tool is intentionally *not* ``read_only`` — the nested
    orchestrator may call mutating tools (via the skill's allow-list),
    so the outer permission dialog still fires even though SkillTool
    itself doesn't mutate state."""

    name = "SkillTool"
    description = (
        "Run a user skill by slug. Skills bundle a prompt with a declared "
        "allowed-tools list. Use this to reuse authored procedures "
        "(e.g. commit, debug) with their permissions enforced."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Skill slug as shown in /skill-list.",
            },
            "arguments": {
                "type": "string",
                "description": "Optional text substituted into $ARGUMENTS.",
            },
        },
        "required": ["slug"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        slug = str(tool_input.get("slug") or "")
        return f"tool:SkillTool:{slug}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        slug = tool_input.get("slug") or "?"
        args = str(tool_input.get("arguments") or "")
        if args:
            return f"Run skill /{slug} with arguments: {args[:120]}"
        return f"Run skill /{slug}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        slug = str(tool_input.get("slug") or "").strip()
        if not slug:
            return ToolResult.failure("SkillTool requires a 'slug'.")
        arguments = str(tool_input.get("arguments") or "")

        depth = int(context.extra.get(SKILL_RECURSION_KEY, 0) or 0)
        if depth >= MAX_SKILL_RECURSION:
            return ToolResult.failure(
                f"SkillTool recursion limit reached ({MAX_SKILL_RECURSION})."
            )

        registry = context.extra.get(SKILL_REGISTRY_KEY)
        skill = registry.get(slug) if registry is not None else None
        if skill is None:
            return ToolResult.failure(
                f"Unknown skill: {slug!r}. Use /skill-list to see available skills."
            )

        expanded_prompt = skill.render_prompt(arguments)
        factory = context.extra.get(ORCHESTRATOR_FACTORY_KEY)
        if factory is None:
            # No nested LLM loop bound — return the expanded prompt so the
            # outer model can finish the work itself. This keeps the tool
            # usable in headless smoke runs.
            return ToolResult.success(
                f"[Skill '{skill.name}' expansion — execute the steps below]\n\n"
                f"{expanded_prompt}",
                skill_slug=skill.slug,
                nested=False,
            )

        allowlist = skill.tool_allowlist()
        from cli.user_skills.allowlist import scoped_allowlist

        # Build the nested orchestrator via the factory. Pass through the
        # recursion depth so nested SkillTool calls inherit the cap.
        nested_context_extra = {
            **context.extra,
            SKILL_RECURSION_KEY: depth + 1,
        }
        nested_orchestrator = factory(
            system_prompt=_skill_system_prompt(skill),
            context_extra=nested_context_extra,
        )

        permissions = getattr(nested_orchestrator, "permissions", None)
        if permissions is None:
            return ToolResult.failure(
                "SkillTool: nested orchestrator did not expose a permission manager."
            )

        with scoped_allowlist(permissions, allowed=allowlist):
            try:
                result = nested_orchestrator.run_turn(expanded_prompt)
            except Exception as exc:  # noqa: BLE001 — surface to model
                return ToolResult.failure(
                    f"SkillTool nested turn failed: {exc}"
                )

        return ToolResult.success(
            result.assistant_text or "(skill completed with no output)",
            skill_slug=skill.slug,
            nested=True,
            nested_tool_calls=len(getattr(result, "tool_executions", []) or []),
            nested_stop_reason=getattr(result, "stop_reason", "end_turn"),
        )


def _skill_system_prompt(skill: Any) -> str:
    """Build the system prompt for the nested orchestrator turn.

    We prepend a short note that the nested turn is a skill invocation
    so the model distinguishes it from an ordinary user prompt. This
    matters most for skills with empty ``allowed_tools`` — the model
    should realise it has no tools available and answer from
    reasoning alone."""
    return (
        f"You are running the '{skill.name}' skill as a tool call from a "
        f"parent agent. Stay on task. Allowed tools: "
        f"{', '.join(skill.allowed_tools) if skill.allowed_tools else '(none)'}."
    )


__all__ = [
    "MAX_SKILL_RECURSION",
    "ORCHESTRATOR_FACTORY_KEY",
    "SKILL_RECURSION_KEY",
    "SKILL_REGISTRY_KEY",
    "SkillTool",
]
