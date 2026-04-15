"""Slash-command integration for user skills.

Two entry points:

* ``/skill <slug> [args]`` — explicit dispatcher; works even when a slug
  would collide with a built-in command.
* ``/skills`` — lists the loaded skills; this name collides with the
  existing coordinator ``/skills`` command, so we register under
  ``/skill-list`` to avoid breaking that flow. Callers who want the
  Claude-Code-style ``/skills`` behaviour can register the same command
  under an alias once we decide to retire the coordinator one.

The dispatcher doesn't yet call the LLM — that lands with the full tool-
use loop in Phase 7. For now it:

1. Resolves the slug against the active :class:`SkillRegistry`.
2. Applies the allow-list via :func:`scoped_allowlist` so any tool calls
   made later in the same turn respect the skill's declared surface.
3. Emits the rendered prompt (``skill.render_prompt(args)``) as a
   transcript entry so the user can verify what would be sent to the
   model. Once the LLM loop is wired the handler switches from "emit
   prompt" to "enqueue prompt for next turn".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done

if TYPE_CHECKING:
    from cli.user_skills.registry import SkillRegistry
    from cli.workbench_app.slash import SlashContext


SKILL_REGISTRY_META_KEY = "skill_registry"


def build_skill_command() -> LocalCommand:
    """``/skill <slug>`` — invoke a loaded skill explicitly."""
    return LocalCommand(
        name="skill",
        description="Invoke a user-loaded skill by slug",
        handler=_handle_skill,
        source="builtin",
        argument_hint="<slug> [arguments]",
        when_to_use=(
            "Use to run a markdown skill from .agentlab/skills. "
            "Arguments are substituted into $ARGUMENTS in the skill body."
        ),
    )


def build_skill_list_command() -> LocalCommand:
    """``/skill-list`` — show the loaded skill catalogue."""
    return LocalCommand(
        name="skill-list",
        description="List user-loaded skills from .agentlab/skills",
        handler=_handle_skill_list,
        source="builtin",
        argument_hint="",
    )


def build_skill_reload_command() -> LocalCommand:
    """``/skill-reload`` — re-scan disk for new or edited skills."""
    return LocalCommand(
        name="skill-reload",
        description="Rescan the skill directories for new or changed skills",
        handler=_handle_skill_reload,
        source="builtin",
    )


def all_skill_commands() -> tuple[LocalCommand, ...]:
    return (
        build_skill_command(),
        build_skill_list_command(),
        build_skill_reload_command(),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_skill(ctx: "SlashContext", *args: str) -> OnDoneResult:
    registry = _registry_from_ctx(ctx)
    if registry is None:
        return _registry_missing()
    if not args:
        return on_done(
            theme.meta("  Usage: /skill <slug> [arguments]. Use /skill-list to see what's loaded."),
            display="system",
        )

    slug = args[0].strip()
    skill_args = " ".join(args[1:]).strip()
    skill = registry.get(slug)
    if skill is None:
        return on_done(
            theme.warning(f"  Unknown skill: {slug}. Try /skill-list."),
            display="system",
        )

    rendered_prompt = skill.render_prompt(skill_args)
    lines = [
        theme.workspace(f"Skill: {skill.name}"),
        theme.meta(
            f"  source: {skill.source.value}"
            + (f"  path: {skill.path}" if skill.path else "")
        ),
    ]
    if skill.allowed_tools:
        lines.append(
            theme.meta("  allowed tools: " + ", ".join(skill.allowed_tools))
        )
    if skill.description:
        lines.append(theme.meta(f"  {skill.description}"))
    lines.append("")
    lines.append("  Prompt that will be sent to the model:")
    lines.append("")
    for body_line in rendered_prompt.splitlines() or [""]:
        lines.append(f"    {body_line}")
    lines.append("")
    lines.append(
        theme.meta(
            "  (Phase-7 LLM loop will forward this prompt automatically; "
            "for now it's shown for inspection.)"
        )
    )
    # Bubble the resolved prompt up to the caller in case a custom loop
    # wants to feed it to a model immediately. The default dispatch path
    # ignores ``meta_messages`` beyond echoing, so this is a no-op there.
    return on_done(
        "\n".join(lines),
        display="user",
        meta_messages=(f"skill.prompt:{slug}",),
    )


def _handle_skill_list(ctx: "SlashContext", *_: str) -> OnDoneResult:
    registry = _registry_from_ctx(ctx)
    if registry is None:
        return _registry_missing()
    skills = registry.list()
    if not skills:
        return on_done(
            theme.meta("  No skills loaded. Drop markdown files in .agentlab/skills/ to add some."),
            display="system",
        )
    lines = [theme.workspace("Loaded skills")]
    for skill in skills:
        tag = f"[{skill.source.value}]"
        summary = skill.description or "(no description)"
        lines.append(f"    /{skill.slug:<18} {tag}  {summary}")
    warnings = registry.warnings
    if warnings:
        lines.append("")
        lines.append(theme.warning("  Load warnings:"))
        for warning in warnings:
            lines.append(f"    {warning}")
    return on_done("\n".join(lines), display="user")


def _handle_skill_reload(ctx: "SlashContext", *_: str) -> OnDoneResult:
    registry = _registry_from_ctx(ctx)
    if registry is None:
        return _registry_missing()
    registry.reload()
    count = len(registry.list())
    message = theme.success(f"  Reloaded skills — {count} available.")
    if registry.warnings:
        message += "\n" + theme.warning(
            f"  {len(registry.warnings)} warning(s) — see /skill-list for details."
        )
    return on_done(message, display="user")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_from_ctx(ctx: "SlashContext") -> "SkillRegistry | None":
    registry = ctx.meta.get(SKILL_REGISTRY_META_KEY) if ctx.meta else None
    # Late import lets tests patch the registry without importing the
    # package at module-load time.
    from cli.user_skills.registry import SkillRegistry

    return registry if isinstance(registry, SkillRegistry) else None


def _registry_missing() -> OnDoneResult:
    return on_done(
        theme.warning(
            "  Skills are not configured for this session. "
            "Re-launch the workbench or set up .agentlab/skills/."
        ),
        display="system",
    )


__all__ = [
    "SKILL_REGISTRY_META_KEY",
    "all_skill_commands",
    "build_skill_command",
    "build_skill_list_command",
    "build_skill_reload_command",
]
