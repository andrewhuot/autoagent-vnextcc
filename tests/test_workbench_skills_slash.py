"""Tests for cli/workbench_app/skills_slash.py (T13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import pytest

from cli.workbench_app.commands import LocalJSXCommand
from cli.workbench_app.screens import ScreenResult, SkillItem, iter_keys
from cli.workbench_app.skills_slash import (
    BackendResult,
    CliSkillsBackend,
    SkillsBackend,
    SkillsScreenAdapter,
    build_skills_command,
)
from cli.workbench_app.slash import SlashContext, dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    def plain(self) -> list[str]:
        return [click.unstyle(line) for line in self.lines]


@dataclass
class _StubBackend(SkillsBackend):
    """Backend that returns canned results so adapter behavior can be asserted."""

    items: list[SkillItem] = field(default_factory=list)
    show_result: BackendResult = BackendResult()
    add_result: BackendResult = BackendResult()
    edit_result: BackendResult = BackendResult()
    remove_result: BackendResult = BackendResult()
    calls: list[tuple[str, tuple]] = field(default_factory=list)

    def list_skills(self) -> list[SkillItem]:
        self.calls.append(("list_skills", ()))
        return list(self.items)

    def show(self, skill_id: str) -> BackendResult:
        self.calls.append(("show", (skill_id,)))
        return self.show_result

    def add(self) -> BackendResult:
        self.calls.append(("add", ()))
        return self.add_result

    def edit(self, skill_id: str) -> BackendResult:
        self.calls.append(("edit", (skill_id,)))
        return self.edit_result

    def remove(self, skill_id: str) -> BackendResult:
        self.calls.append(("remove", (skill_id,)))
        return self.remove_result


def _items() -> list[SkillItem]:
    return [
        SkillItem(skill_id="alpha", name="Alpha", kind="build", description="A."),
        SkillItem(skill_id="beta", name="Beta", kind="runtime", description="B."),
    ]


# ---------------------------------------------------------------------------
# SkillsScreenAdapter — action dispatch
# ---------------------------------------------------------------------------


def test_adapter_exit_key_closes_cleanly() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=_items())
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["q"]), echo=echo)
    result = adapter.run()
    assert result.action == "exit"
    assert result.meta_messages == ()
    assert backend.calls == [("list_skills", ())]


def test_adapter_list_action_surfaces_count_meta() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=_items())
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["l"]), echo=echo)
    result = adapter.run()
    assert result.action == "exit"
    assert result.meta_messages == ("Listed 2 skills",)


def test_adapter_list_singular_when_one_skill() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=[_items()[0]])
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["l"]), echo=echo)
    result = adapter.run()
    assert result.meta_messages == ("Listed 1 skill",)


def test_adapter_show_calls_backend_with_selected_id() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(
        items=_items(),
        show_result=BackendResult(
            lines=("line1", "line2"), summary="Showed skill alpha"
        ),
    )
    # j moves to beta, s shows it.
    adapter = SkillsScreenAdapter(
        backend, keys=iter_keys(["j", "s"]), echo=echo
    )
    result = adapter.run()
    assert backend.calls[-1] == ("show", ("beta",))
    assert "line1" in echo.lines and "line2" in echo.lines
    assert result.meta_messages == ("Showed skill beta",) or result.meta_messages == (
        "Showed skill alpha",
    )


def test_adapter_show_without_items_reports_needs_selection() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=[])
    # Empty list: SkillsScreen shows placeholder. 's' still fires but value is None.
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["s"]), echo=echo)
    result = adapter.run()
    assert any("/show needs a selected skill" in click.unstyle(l) for l in echo.lines)
    assert result.meta_messages == ("/show needs a selected skill",)
    # No show() call when nothing is selected.
    assert all(call[0] != "show" for call in backend.calls)


def test_adapter_add_does_not_require_selection() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(
        items=[],
        add_result=BackendResult(
            lines=(click.style("  Created.", fg="green"),),
            summary="Created skill(s): foo",
        ),
    )
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["a"]), echo=echo)
    result = adapter.run()
    assert backend.calls[-1] == ("add", ())
    assert result.meta_messages == ("Created skill(s): foo",)


def test_adapter_edit_uses_selected_skill() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(
        items=_items(),
        edit_result=BackendResult(
            lines=("edited",), summary="Updated skill alpha"
        ),
    )
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["e"]), echo=echo)
    result = adapter.run()
    assert backend.calls[-1] == ("edit", ("alpha",))
    assert result.meta_messages == ("Updated skill alpha",)


def test_adapter_remove_uses_selected_skill() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(
        items=_items(),
        remove_result=BackendResult(
            lines=("removed.",), summary="Removed skill alpha"
        ),
    )
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["r"]), echo=echo)
    result = adapter.run()
    assert backend.calls[-1] == ("remove", ("alpha",))
    assert result.meta_messages == ("Removed skill alpha",)


def test_adapter_empty_summary_omits_meta() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(
        items=_items(),
        show_result=BackendResult(lines=("only lines",), summary=""),
    )
    adapter = SkillsScreenAdapter(backend, keys=iter_keys(["s"]), echo=echo)
    result = adapter.run()
    assert result.meta_messages == ()


def test_adapter_eof_closes_cleanly() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=_items())
    adapter = SkillsScreenAdapter(backend, keys=iter_keys([]), echo=echo)
    result = adapter.run()
    assert result.action == "exit"


# ---------------------------------------------------------------------------
# build_skills_command + dispatch integration
# ---------------------------------------------------------------------------


def test_build_skills_command_is_local_jsx() -> None:
    command = build_skills_command()
    assert isinstance(command, LocalJSXCommand)
    assert command.name == "skills"
    assert command.kind == "local-jsx"
    assert command.source == "builtin"


def test_dispatch_skills_runs_screen_with_backend() -> None:
    echo = _EchoCapture()
    backend = _StubBackend(items=_items())
    command = build_skills_command(backend=backend)

    # Patch the factory to plug in our key provider, since the production
    # factory defaults to interactive input.
    original_factory = command.screen_factory

    def _factory(ctx, *args):
        screen = original_factory(ctx, *args)
        screen._keys = iter_keys(["l"])  # noqa: SLF001 - test harness
        return screen

    patched = LocalJSXCommand(
        name="skills",
        description=command.description,
        screen_factory=_factory,
        source="builtin",
    )
    from cli.workbench_app.commands import CommandRegistry

    registry = CommandRegistry()
    registry.register(patched)

    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/skills")
    assert result.handled is True
    assert result.display == "system"
    assert result.meta_messages == ("Listed 2 skills",)
    # Meta line echoed as dim.
    assert any("Listed 2 skills" in click.unstyle(l) for l in echo.lines)


# ---------------------------------------------------------------------------
# CliSkillsBackend — exercised with a fake SkillStore so we don't touch sqlite
# ---------------------------------------------------------------------------


@dataclass
class _FakeSkill:
    id: str
    name: str
    description: str
    kind_value: str = "build"
    version: str = "1.0.0"

    @property
    def kind(self) -> Any:
        class _K:
            value = self.kind_value

        return _K

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind_value,
            "version": self.version,
            "description": self.description,
        }


class _FakeStore:
    def __init__(self, skills: list[_FakeSkill]) -> None:
        self._skills = {s.id: s for s in skills}
        self.deleted: list[str] = []
        self.updated: list[str] = []
        self.created: list[_FakeSkill] = []
        self.closed = 0

    def list(self) -> list[_FakeSkill]:
        return list(self._skills.values())

    def get(self, skill_id: str) -> _FakeSkill | None:
        return self._skills.get(skill_id)

    def delete(self, skill_id: str) -> bool:
        self.deleted.append(skill_id)
        return self._skills.pop(skill_id, None) is not None

    def update(self, skill: Any) -> bool:
        self.updated.append(skill.id)
        return True

    def create(self, skill: Any) -> str:
        self.created.append(skill)
        return skill.id

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore(
        [
            _FakeSkill(id="alpha", name="Alpha", description="A skill."),
            _FakeSkill(id="beta", name="Beta", description="Beta skill."),
        ]
    )
    monkeypatch.setattr("cli.skills._get_store", lambda _db=None: store)
    return store


def test_cli_backend_list_skills_projects_to_items(
    fake_store: _FakeStore,
) -> None:
    backend = CliSkillsBackend()
    items = backend.list_skills()
    assert [i.skill_id for i in items] == ["alpha", "beta"]
    assert all(i.kind == "build" for i in items)
    assert fake_store.closed >= 1


def test_cli_backend_show_missing_skill_returns_error(
    fake_store: _FakeStore,
) -> None:
    backend = CliSkillsBackend()
    result = backend.show("missing")
    assert result.error is True
    assert "not found" in click.unstyle(result.lines[0])


def test_cli_backend_show_returns_yaml_body(fake_store: _FakeStore) -> None:
    backend = CliSkillsBackend()
    result = backend.show("alpha")
    assert result.error is False
    body = "\n".join(result.lines)
    assert "id: alpha" in body
    assert "name: Alpha" in body
    assert result.summary == "Showed skill alpha"


def test_cli_backend_remove_cancels_when_confirmer_returns_false(
    fake_store: _FakeStore,
) -> None:
    backend = CliSkillsBackend(confirmer=lambda _msg: False)
    result = backend.remove("alpha")
    assert result.error is False
    assert "cancelled" in click.unstyle(result.lines[0]).lower()
    # No delete attempted.
    assert fake_store.deleted == []


def test_cli_backend_remove_deletes_on_confirm(fake_store: _FakeStore) -> None:
    backend = CliSkillsBackend(confirmer=lambda _msg: True)
    result = backend.remove("alpha")
    assert result.error is False
    assert fake_store.deleted == ["alpha"]
    assert result.summary == "Removed skill alpha"


def test_cli_backend_remove_missing_skill(fake_store: _FakeStore) -> None:
    backend = CliSkillsBackend(confirmer=lambda _msg: True)
    result = backend.remove("missing")
    assert result.error is True
    assert fake_store.deleted == ["missing"]


def test_cli_backend_edit_aborts_on_editor_nonzero_exit(
    fake_store: _FakeStore,
) -> None:
    backend = CliSkillsBackend(editor_runner=lambda _p: 1)
    result = backend.edit("alpha")
    assert result.error is True
    assert "status 1" in click.unstyle(result.lines[0])
    assert fake_store.updated == []


def test_cli_backend_edit_saves_after_successful_editor(
    fake_store: _FakeStore,
) -> None:
    seen_paths: list[Path] = []

    def _editor(path: Path) -> int:
        seen_paths.append(path)
        # Leave the file unchanged — the dump we pre-wrote is valid YAML.
        return 0

    backend = CliSkillsBackend(editor_runner=_editor)
    result = backend.edit("alpha")
    assert result.error is False, result.lines
    assert fake_store.updated == ["alpha"]
    assert seen_paths and not seen_paths[0].exists()  # cleaned up


def test_cli_backend_edit_missing_skill(fake_store: _FakeStore) -> None:
    backend = CliSkillsBackend(editor_runner=lambda _p: 0)
    result = backend.edit("missing")
    assert result.error is True
    assert "not found" in click.unstyle(result.lines[0])


def test_cli_backend_add_aborts_on_editor_nonzero(fake_store: _FakeStore) -> None:
    backend = CliSkillsBackend(editor_runner=lambda _p: 2)
    result = backend.add()
    assert result.error is True
    assert fake_store.created == []


def test_cli_backend_add_creates_from_editor_buffer(
    fake_store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feed a minimal valid skills YAML via the editor "edit".
    yaml_payload = (
        "skills:\n"
        "  - id: gamma\n"
        "    name: Gamma\n"
        "    kind: build\n"
        "    version: 1.0.0\n"
        "    description: New one\n"
    )

    def _editor(path: Path) -> int:
        path.write_text(yaml_payload, encoding="utf-8")
        return 0

    # SkillLoader lives in core.skills.loader — patch it to a trivial stub
    # so we don't depend on the real loader's schema.
    class _StubSkill:
        def __init__(self) -> None:
            self.id = "gamma"

    class _StubLoader:
        def load_from_yaml(self, _path: str) -> list[_StubSkill]:
            return [_StubSkill()]

    monkeypatch.setattr(
        "core.skills.loader.SkillLoader", lambda: _StubLoader()
    )

    backend = CliSkillsBackend(editor_runner=_editor)
    result = backend.add()
    assert result.error is False, result.lines
    assert [s.id for s in fake_store.created] == ["gamma"]
    assert "Created skill(s): gamma" in result.summary
