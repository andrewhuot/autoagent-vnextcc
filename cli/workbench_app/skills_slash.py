"""``/skills`` — full-screen skill manager.

Mirrors Claude Code's ``SkillsMenu`` (``src/screens/SkillsMenu.tsx``): a
navigable list of installed skills plus action keys
``l`` (list), ``s`` (show), ``a`` (add), ``e`` (edit), ``r`` (remove).
Registered as a :class:`LocalJSXCommand` so the workbench dispatch layer
hands control over to the screen until the user exits.

Design
------

The screen itself (:class:`cli.workbench_app.screens.skills.SkillsScreen`)
only tracks cursor + action selection; it deliberately knows nothing about
how actions are carried out. This module fills in the gap with:

- :class:`SkillsBackend` — protocol describing the four imperatives
  (``list_skills`` / ``show`` / ``edit`` / ``add`` / ``remove``). The default
  implementation (:class:`CliSkillsBackend`) delegates to
  :mod:`core.skills.store` via the helpers in :mod:`cli.skills`.
- :class:`SkillsScreenAdapter` — wraps a :class:`SkillsScreen` with the
  action dispatch loop: run the screen, carry out the returned action via
  the backend, echo result lines to the transcript, and surface a summary
  line through the :class:`ScreenResult.meta_messages` contract so dispatch
  renders it as a dim meta entry on return.

``$EDITOR``/``$VISUAL`` launching is isolated behind the :data:`EditorRunner`
seam so tests drive the flow without spawning a real editor — the default
shells out to :func:`subprocess.call` with ``EDITOR`` (falling back to
``VISUAL`` and then ``vi``). Confirmation before ``remove`` is similarly
behind a :data:`Confirmer` seam defaulting to :func:`click.confirm`.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import click

from cli.workbench_app.commands import LocalJSXCommand
from cli.workbench_app.screens.base import (
    ACTION_CANCEL,
    ACTION_EXIT,
    EchoFn,
    KeyProvider,
    Screen,
    ScreenResult,
)
from cli.workbench_app.screens.skills import SkillItem, SkillsScreen


EditorRunner = Callable[[Path], int]
"""Open ``path`` in ``$EDITOR`` and return the exit status."""

Confirmer = Callable[[str], bool]
"""Ask for ``y/N`` confirmation; return ``True`` to proceed."""


class EditorError(RuntimeError):
    """Raised when the configured editor cannot be launched."""


@dataclass(frozen=True)
class BackendResult:
    """Payload returned by each :class:`SkillsBackend` action.

    ``lines`` is echoed verbatim to the transcript (already styled as needed
    by the backend). ``summary`` becomes a dim meta line once the screen
    closes, summarising what happened. ``error`` flips the summary to the
    error style when rendered.
    """

    lines: tuple[str, ...] = ()
    summary: str = ""
    error: bool = False


class SkillsBackend(Protocol):
    """Operations the ``/skills`` screen needs from the skill store.

    Every method returns a :class:`BackendResult` so the adapter can render
    output uniformly without caring whether the action called into the
    store, launched the editor, or failed. Implementations must clean up
    their own resources (store handles, temp files) — the adapter makes no
    assumptions about lifecycles.
    """

    def list_skills(self) -> list[SkillItem]: ...

    def show(self, skill_id: str) -> BackendResult: ...

    def add(self) -> BackendResult: ...

    def edit(self, skill_id: str) -> BackendResult: ...

    def remove(self, skill_id: str) -> BackendResult: ...


# ---------------------------------------------------------------------------
# Default backend — delegates to core.skills.store / cli.skills.
# ---------------------------------------------------------------------------


def _default_editor_runner(path: Path) -> int:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        return subprocess.call([editor, str(path)])
    except OSError as exc:  # pragma: no cover - trivial shim
        raise EditorError(f"could not launch editor {editor!r}: {exc}") from exc


def _default_confirmer(message: str) -> bool:
    try:
        return bool(click.confirm(message, default=False))
    except click.Abort:
        return False
    except (KeyboardInterrupt, EOFError):
        return False


def _skill_to_item(skill: Any) -> SkillItem:
    """Project a :class:`core.skills.types.Skill` record into a UI row."""
    description = (skill.description or "").strip().splitlines()
    first_line = description[0][:80] if description else ""
    kind = skill.kind.value if hasattr(skill.kind, "value") else str(skill.kind)
    return SkillItem(
        skill_id=skill.id,
        name=skill.name,
        kind=kind,
        description=first_line,
    )


@dataclass
class CliSkillsBackend:
    """Default :class:`SkillsBackend` backed by :mod:`core.skills.store`.

    ``db_path`` threads through to :func:`cli.skills._get_store` so callers
    can point at an alternate database during tests. ``editor_runner`` and
    ``confirmer`` are injectable for tests that want to exercise add/edit
    without a TTY or confirm prompt.
    """

    db_path: str | None = None
    editor_runner: EditorRunner = field(default=_default_editor_runner)
    confirmer: Confirmer = field(default=_default_confirmer)

    # ------------------------------------------------------------------ helpers

    def _store(self):
        from cli.skills import _get_store

        return _get_store(self.db_path)

    # ------------------------------------------------------------------ list

    def list_skills(self) -> list[SkillItem]:
        store = self._store()
        try:
            return [_skill_to_item(s) for s in store.list()]
        finally:
            store.close()

    # ------------------------------------------------------------------ show

    def show(self, skill_id: str) -> BackendResult:
        import yaml

        store = self._store()
        try:
            skill = store.get(skill_id)
        finally:
            store.close()
        if skill is None:
            message = f"  Skill not found: {skill_id}"
            return BackendResult(
                lines=(click.style(message, fg="red"),),
                summary=f"Show failed: {skill_id} not found",
                error=True,
            )
        body = yaml.dump(
            skill.to_dict(),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        return BackendResult(
            lines=tuple(body.rstrip().splitlines()),
            summary=f"Showed skill {skill_id}",
        )

    # ------------------------------------------------------------------ add

    def add(self) -> BackendResult:
        import yaml

        from core.skills.loader import SkillLoader

        template = {
            "skills": [
                {
                    "id": "new_skill",
                    "name": "New Skill",
                    "kind": "build",
                    "version": "1.0.0",
                    "description": "Describe what this skill does.",
                    "domain": "general",
                    "tags": [],
                }
            ]
        }
        tmp_path = _write_editor_buffer(yaml.dump(template, sort_keys=False))
        try:
            rc = self.editor_runner(tmp_path)
            if rc != 0:
                return BackendResult(
                    lines=(
                        click.style(
                            f"  Editor exited with status {rc}; skill not created.",
                            fg="yellow",
                        ),
                    ),
                    summary="Add aborted by editor",
                    error=True,
                )
            loader = SkillLoader()
            skills = loader.load_from_yaml(str(tmp_path))
            if not skills:
                return BackendResult(
                    lines=(
                        click.style(
                            "  No skills parsed from editor buffer — nothing to create.",
                            fg="yellow",
                        ),
                    ),
                    summary="Add produced no skills",
                    error=True,
                )
            store = self._store()
            try:
                created = [store.create(s) for s in skills]
            finally:
                store.close()
            names = ", ".join(created)
            return BackendResult(
                lines=(
                    click.style(f"  Created skill(s): {names}", fg="green"),
                ),
                summary=f"Created skill(s): {names}",
            )
        finally:
            _unlink_quiet(tmp_path)

    # ------------------------------------------------------------------ edit

    def edit(self, skill_id: str) -> BackendResult:
        import yaml

        from core.skills.types import Skill

        store = self._store()
        try:
            skill = store.get(skill_id)
        finally:
            store.close()
        if skill is None:
            return BackendResult(
                lines=(click.style(f"  Skill not found: {skill_id}", fg="red"),),
                summary=f"Edit failed: {skill_id} not found",
                error=True,
            )
        tmp_path = _write_editor_buffer(
            yaml.dump(skill.to_dict(), sort_keys=False, allow_unicode=True)
        )
        try:
            rc = self.editor_runner(tmp_path)
            if rc != 0:
                return BackendResult(
                    lines=(
                        click.style(
                            f"  Editor exited with status {rc}; skill not modified.",
                            fg="yellow",
                        ),
                    ),
                    summary=f"Edit aborted: {skill_id}",
                    error=True,
                )
            try:
                data = yaml.safe_load(tmp_path.read_text(encoding="utf-8"))
                updated = Skill.from_dict(data)
            except Exception as exc:
                return BackendResult(
                    lines=(
                        click.style(
                            f"  Could not parse edited skill: {exc}", fg="red"
                        ),
                    ),
                    summary=f"Edit failed: {skill_id} parse error",
                    error=True,
                )
            store = self._store()
            try:
                ok = store.update(updated)
            finally:
                store.close()
            if not ok:
                return BackendResult(
                    lines=(
                        click.style(
                            f"  Update failed for skill: {skill_id}", fg="red"
                        ),
                    ),
                    summary=f"Edit failed: {skill_id}",
                    error=True,
                )
            return BackendResult(
                lines=(click.style(f"  Updated skill: {skill_id}", fg="green"),),
                summary=f"Updated skill {skill_id}",
            )
        finally:
            _unlink_quiet(tmp_path)

    # ------------------------------------------------------------------ remove

    def remove(self, skill_id: str) -> BackendResult:
        if not self.confirmer(f"Remove skill {skill_id}?"):
            return BackendResult(
                lines=(
                    click.style(
                        f"  Remove cancelled: {skill_id}", fg="yellow"
                    ),
                ),
                summary=f"Remove cancelled: {skill_id}",
            )
        store = self._store()
        try:
            ok = store.delete(skill_id)
        finally:
            store.close()
        if not ok:
            return BackendResult(
                lines=(click.style(f"  Skill not found: {skill_id}", fg="red"),),
                summary=f"Remove failed: {skill_id} not found",
                error=True,
            )
        return BackendResult(
            lines=(click.style(f"  Removed skill: {skill_id}", fg="green"),),
            summary=f"Removed skill {skill_id}",
        )


def _write_editor_buffer(contents: str) -> Path:
    """Drop ``contents`` into a temp YAML file and return its path."""
    fd, name = tempfile.mkstemp(prefix="agentlab-skill-", suffix=".yaml")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(contents)
    except Exception:
        _unlink_quiet(path)
        raise
    return path


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:  # pragma: no cover - best effort cleanup
        pass


# ---------------------------------------------------------------------------
# Screen adapter — turns SkillsScreen into a LocalJSXCommand screen factory.
# ---------------------------------------------------------------------------


class SkillsScreenAdapter(Screen):
    """Run :class:`SkillsScreen` once, then carry out the returned action.

    Designed as a single-shot flow: the user picks one action
    (``show``/``add``/``edit``/``remove``/``list``) and the screen closes.
    Re-invoking ``/skills`` launches a fresh screen with the latest state.
    This keeps the base :class:`Screen` loop trivially testable — no nested
    re-paint orchestration.
    """

    name = "skills"
    title = "/skills"

    def __init__(
        self,
        backend: SkillsBackend,
        *,
        keys: KeyProvider | Sequence[str] | None = None,
        echo: EchoFn | None = None,
    ) -> None:
        super().__init__(keys=keys, echo=echo)
        self._backend = backend

    # The adapter doesn't render anything itself — the inner SkillsScreen
    # paints. We still satisfy the abstract methods so Screen's type
    # contract holds.
    def render_lines(self) -> list[str]:  # pragma: no cover - unused
        return []

    def handle_key(self, key: str) -> ScreenResult | None:  # pragma: no cover
        return None

    def run(self) -> ScreenResult:  # type: ignore[override]
        items = self._backend.list_skills()
        screen = SkillsScreen(items, keys=self._keys, echo=self._echo)
        result = screen.run()
        action = result.action

        if action in {ACTION_EXIT, ACTION_CANCEL}:
            return ScreenResult(action=ACTION_EXIT)

        if action == "list":
            summary = f"Listed {len(items)} skill{'s' if len(items) != 1 else ''}"
            return ScreenResult(action=ACTION_EXIT, meta_messages=(summary,))

        if action == "add":
            outcome = self._backend.add()
            return self._carry_out(outcome)

        skill_id = result.value
        if skill_id is None:
            summary = f"/{action} needs a selected skill"
            self._echo(
                click.style(f"  {summary}", fg="yellow")
            )
            return ScreenResult(
                action=ACTION_EXIT,
                meta_messages=(summary,),
            )

        if action == "show":
            return self._carry_out(self._backend.show(skill_id))
        if action == "edit":
            return self._carry_out(self._backend.edit(skill_id))
        if action == "remove":
            return self._carry_out(self._backend.remove(skill_id))

        # Unknown action — safest behaviour is to close cleanly with a note.
        return ScreenResult(
            action=ACTION_EXIT,
            meta_messages=(f"Unhandled /skills action: {action}",),
        )

    def _carry_out(self, outcome: BackendResult) -> ScreenResult:
        for line in outcome.lines:
            self._echo(line)
        meta = (outcome.summary,) if outcome.summary else ()
        return ScreenResult(action=ACTION_EXIT, meta_messages=meta)


# ---------------------------------------------------------------------------
# Factory + LocalJSXCommand registration
# ---------------------------------------------------------------------------


def build_skills_command(
    *,
    backend: SkillsBackend | None = None,
) -> LocalJSXCommand:
    """Return the :class:`LocalJSXCommand` wiring for ``/skills``.

    The optional ``backend`` override lets tests and integrators drop in a
    stub without subclassing or patching. Production callers omit it and
    get :class:`CliSkillsBackend`.
    """
    default_backend: SkillsBackend = backend if backend is not None else CliSkillsBackend()

    def _factory(ctx: Any, *_args: str) -> SkillsScreenAdapter:
        # The dispatch layer passes the SlashContext + remaining args; we
        # only need the echo channel for now so we thread it through.
        echo: EchoFn | None = getattr(ctx, "echo", None)
        return SkillsScreenAdapter(default_backend, echo=echo)

    return LocalJSXCommand(
        name="skills",
        description="Browse, show, add, edit, or remove skills",
        screen_factory=_factory,
        source="builtin",
        argument_hint="[list|show|add|edit|remove]",
        when_to_use="Use when you need to inspect or maintain configured skills.",
    )


__all__ = [
    "BackendResult",
    "CliSkillsBackend",
    "Confirmer",
    "EditorError",
    "EditorRunner",
    "SkillsBackend",
    "SkillsScreenAdapter",
    "build_skills_command",
]
