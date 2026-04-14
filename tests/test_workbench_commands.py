"""Tests for cli/workbench_app/commands.py — three-tier slash-command taxonomy."""

from __future__ import annotations

import pytest

from cli.workbench_app.commands import (
    CommandRegistry,
    LocalCommand,
    LocalJSXCommand,
    PromptCommand,
    build_default_registry,
)


class _StubScreen:
    def __init__(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code

    def run(self) -> int:
        return self._exit_code


def _noop_handler(*_: object, **__: object) -> str:
    return "ok"


# ---------------------------------------------------------------------------
# LocalCommand
# ---------------------------------------------------------------------------


def test_local_command_requires_handler() -> None:
    with pytest.raises(ValueError, match="requires a handler"):
        LocalCommand(name="status", description="Show status")


def test_local_command_kind_discriminator() -> None:
    cmd = LocalCommand(
        name="status", description="Show status", handler=_noop_handler
    )
    assert cmd.kind == "local"
    assert cmd.source == "builtin"
    assert cmd.context == "inline"


def test_local_command_rejects_leading_slash() -> None:
    with pytest.raises(ValueError, match="not include the leading"):
        LocalCommand(name="/status", description="bad", handler=_noop_handler)


def test_local_command_rejects_whitespace_in_name() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        LocalCommand(name="foo bar", description="bad", handler=_noop_handler)


def test_local_command_accepts_aliases_and_metadata() -> None:
    cmd = LocalCommand(
        name="eval",
        description="Run eval",
        handler=_noop_handler,
        aliases=("e",),
        argument_hint="[--config VERSION]",
        when_to_use="Run this after changing an evaluator or prompt.",
        source="project",
        effort="medium",
        allowed_tools=("bash",),
        immediate=True,
        sensitive=True,
    )
    assert cmd.aliases == ("e",)
    assert cmd.argument_hint == "[--config VERSION]"
    assert "changing an evaluator" in cmd.when_to_use
    assert cmd.effort == "medium"
    assert cmd.allowed_tools == ("bash",)
    assert cmd.immediate is True
    assert cmd.sensitive is True


# ---------------------------------------------------------------------------
# LocalJSXCommand
# ---------------------------------------------------------------------------


def test_local_jsx_command_requires_screen_factory() -> None:
    with pytest.raises(ValueError, match="requires a screen_factory"):
        LocalJSXCommand(name="skills", description="Browse skills")


def test_local_jsx_command_kind_discriminator() -> None:
    cmd = LocalJSXCommand(
        name="skills",
        description="Browse skills",
        screen_factory=_StubScreen,
    )
    assert cmd.kind == "local-jsx"
    screen = cmd.screen_factory()
    assert screen.run() == 0


# ---------------------------------------------------------------------------
# PromptCommand
# ---------------------------------------------------------------------------


def test_prompt_command_requires_template() -> None:
    with pytest.raises(ValueError, match="requires a prompt_template"):
        PromptCommand(name="explain", description="Explain code")


def test_prompt_command_renders_static_template() -> None:
    cmd = PromptCommand(
        name="explain",
        description="Explain a file",
        prompt_template="Explain {path}",
    )
    assert cmd.kind == "prompt"
    assert cmd.render(path="runner.py") == "Explain runner.py"


def test_prompt_command_renders_callable_template() -> None:
    cmd = PromptCommand(
        name="summary",
        description="Summarize a diff",
        prompt_template=lambda *, files: "Summarize " + ", ".join(files),
    )
    assert cmd.render(files=["a.py", "b.py"]) == "Summarize a.py, b.py"


def test_prompt_command_rejects_non_string_output() -> None:
    cmd = PromptCommand(
        name="bad",
        description="Broken",
        prompt_template=lambda: 42,  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(TypeError, match="non-string"):
        cmd.render()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _make_local(name: str, **kwargs: object) -> LocalCommand:
    return LocalCommand(
        name=name,
        description=f"{name} command",
        handler=_noop_handler,
        **kwargs,  # type: ignore[arg-type]
    )


def test_registry_register_and_lookup_case_insensitive() -> None:
    registry = CommandRegistry()
    cmd = registry.register(_make_local("Status"))
    assert registry.get("/status") is cmd
    assert registry.get("STATUS") is cmd
    assert "/status" in registry
    assert len(registry) == 1


def test_registry_rejects_duplicate_name() -> None:
    registry = CommandRegistry()
    registry.register(_make_local("status"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_make_local("status"))


def test_registry_rejects_alias_collision() -> None:
    registry = CommandRegistry()
    registry.register(_make_local("status"))
    with pytest.raises(ValueError, match="conflicts"):
        registry.register(_make_local("show", aliases=("status",)))


def test_registry_alias_resolves_to_canonical_command() -> None:
    registry = CommandRegistry()
    cmd = registry.register(_make_local("eval", aliases=("e", "run-eval")))
    assert registry.get("/e") is cmd
    assert registry.get("run-eval") is cmd


def test_registry_replace_overwrites() -> None:
    registry = CommandRegistry()
    first = registry.register(_make_local("status"))
    replacement = LocalCommand(
        name="status",
        description="Updated",
        handler=_noop_handler,
        source="user",
    )
    registry.replace(replacement)
    found = registry.get("/status")
    assert found is replacement
    assert found is not first
    assert found.source == "user"


def test_registry_unregister_missing_raises() -> None:
    registry = CommandRegistry()
    with pytest.raises(KeyError):
        registry.unregister("nope")
    # missing_ok should swallow
    registry.unregister("nope", missing_ok=True)


def test_registry_filters_by_source_and_kind() -> None:
    registry = build_default_registry(
        [
            _make_local("status"),
            _make_local("project-cmd", source="project"),
            LocalJSXCommand(
                name="skills",
                description="Browse",
                screen_factory=_StubScreen,
            ),
            PromptCommand(
                name="explain",
                description="Explain",
                prompt_template="Explain {path}",
            ),
        ]
    )
    assert {c.name for c in registry.by_source("builtin")} == {
        "status",
        "skills",
        "explain",
    }
    assert [c.name for c in registry.by_source("project")] == ["project-cmd"]
    assert [c.name for c in registry.by_kind("local-jsx")] == ["skills"]
    assert [c.name for c in registry.by_kind("prompt")] == ["explain"]


def test_registry_match_prefix_includes_aliases() -> None:
    registry = CommandRegistry()
    registry.register(_make_local("eval", aliases=("e",)))
    registry.register(_make_local("edit"))
    registry.register(_make_local("status"))

    by_e = [c.name for c in registry.match_prefix("/e")]
    assert by_e == ["edit", "eval"]

    by_ev = [c.name for c in registry.match_prefix("ev")]
    assert by_ev == ["eval"]

    assert registry.match_prefix("zzz") == []


def test_registry_help_table_formats_slash_prefix() -> None:
    registry = CommandRegistry()
    registry.register(_make_local("status"))
    registry.register(
        LocalJSXCommand(
            name="skills",
            description="Browse skills",
            screen_factory=_StubScreen,
        )
    )
    table = registry.help_table()
    assert table["/status"] == "status command"
    assert table["/skills"] == "Browse skills"


def test_registry_visibility_filters_hidden_commands_from_discovery() -> None:
    """Hidden commands still dispatch directly but stay out of help/popups."""

    registry = CommandRegistry()
    visible = registry.register(_make_local("status"))
    hidden = registry.register(_make_local("debug-internal", hidden=True))

    assert registry.get("/debug-internal") is hidden
    assert registry.visible() == [visible]
    assert registry.match_prefix("/debug") == []
    assert registry.match_prefix("/debug", include_hidden=True) == [hidden]
    assert "/debug-internal" not in registry.help_table()


def test_registry_iter_sorted_by_name() -> None:
    registry = build_default_registry(
        [_make_local("zeta"), _make_local("alpha"), _make_local("mu")]
    )
    assert [c.name for c in registry] == ["alpha", "mu", "zeta"]
    assert registry.names() == ["alpha", "mu", "zeta"]
