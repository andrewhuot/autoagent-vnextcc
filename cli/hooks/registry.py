"""Hook registry and runner.

:class:`HookRegistry` reads the ``hooks`` block from ``settings.json``
(loaded via :mod:`cli.permissions`) and exposes :meth:`fire` for the
tool executor. The runner shells out to each hook's command with the
event payload JSON-encoded on stdin, captures stdout/stderr, and
aggregates the results into a :class:`HookOutcome`.

Keeping the runner in the registry (rather than a separate executor
class) avoids a second layer of orchestration for a problem that's
fundamentally "run N subprocesses"; tests that need fine-grained
control pass a custom ``runner`` callable.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from cli.hooks.types import (
    HookDefinition,
    HookEvent,
    HookOutcome,
    HookType,
    HookVerdict,
)


Runner = Callable[[HookDefinition, dict[str, Any]], "HookProcessResult"]


@dataclass
class HookProcessResult:
    """Output of running one hook — consumed by :class:`HookRegistry`."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class HookRegistry:
    """Collection of :class:`HookDefinition` keyed by event.

    The registry is built from a ``hooks`` mapping (typically loaded from
    ``settings.json``) via :func:`load_hook_registry`. Tests that need
    fine-grained control can build an instance directly by appending to
    :attr:`definitions`.
    """

    definitions: dict[HookEvent, list[HookDefinition]] = field(default_factory=dict)
    runner: Runner | None = None

    def add(self, definition: HookDefinition) -> None:
        self.definitions.setdefault(definition.event, []).append(definition)

    def hooks_for(self, event: HookEvent, *, tool_name: str = "") -> list[HookDefinition]:
        """Return the hooks subscribed to ``event`` that match ``tool_name``."""
        return [
            hook
            for hook in self.definitions.get(event, [])
            if hook.matches_tool(tool_name)
        ]

    def prompt_fragments_for(
        self,
        event: HookEvent,
        *,
        tool_name: str = "",
    ) -> list[str]:
        """Return distinct prompt fragments subscribed to ``event``.

        Deduplicates via :meth:`HookDefinition.resolved_id` so a rule that
        matches every tool (``matcher=""``) doesn't flood the model call
        with copies of the same text. Returns fragments in registration
        order to keep injection deterministic."""
        seen: set[str] = set()
        fragments: list[str] = []
        for hook in self.hooks_for(event, tool_name=tool_name):
            if hook.hook_type is not HookType.PROMPT:
                continue
            fragment = (hook.prompt or "").strip()
            if not fragment:
                continue
            fingerprint = hook.resolved_id()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            fragments.append(fragment)
        return fragments

    def fire(
        self,
        event: HookEvent,
        *,
        tool_name: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> HookOutcome:
        """Run every matching *command* hook in order. Aggregate into one outcome.

        Hooks run sequentially. A gating event (``PreToolUse`` or
        ``OnPermissionRequest``) short-circuits on the first deny so
        subsequent hooks for the same event are skipped — matching
        Claude Code's "first deny wins" semantics. Prompt-type hooks are
        ignored here; see :meth:`prompt_fragments_for`."""
        outcome = HookOutcome()
        hooks = [
            hook
            for hook in self.hooks_for(event, tool_name=tool_name)
            if hook.hook_type is HookType.COMMAND
        ]
        if not hooks:
            return outcome

        runner = self.runner or _default_runner
        gating = event in {HookEvent.PRE_TOOL_USE, HookEvent.ON_PERMISSION_REQUEST}
        payload_dict = dict(payload or {})

        for hook in hooks:
            result = runner(hook, payload_dict)
            outcome.record_fired()
            message = result.stderr.strip() or result.stdout.strip()
            if result.timed_out:
                outcome.record_deny(
                    f"Hook {hook.command!r} timed out after {hook.timeout_seconds}s."
                )
                if gating:
                    break
                continue
            if result.returncode == 0:
                if message:
                    outcome.record_inform(message)
            else:
                outcome.record_deny(message or f"Hook exited {result.returncode}")
                if gating:
                    break

        return outcome


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _default_runner(hook: HookDefinition, payload: dict[str, Any]) -> HookProcessResult:
    """Run a hook via ``bash -c`` (or the configured shell) with payload on stdin."""
    env = os.environ.copy()
    env.update(hook.env)
    try:
        completed = subprocess.run(
            [hook.shell, "-c", hook.command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=hook.timeout_seconds,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return HookProcessResult(
            returncode=127,
            stdout="",
            stderr=f"hook shell not available: {hook.shell!r}",
        )
    except subprocess.TimeoutExpired:
        return HookProcessResult(
            returncode=124,
            stdout="",
            stderr="",
            timed_out=True,
        )
    return HookProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


# ---------------------------------------------------------------------------
# Loading from settings
# ---------------------------------------------------------------------------


def load_hook_registry(
    settings: Mapping[str, Any],
    *,
    runner: Runner | None = None,
) -> HookRegistry:
    """Build a :class:`HookRegistry` from a parsed ``settings.json`` dict.

    The shape mirrors Claude Code's:

    .. code-block:: json

       {
         "hooks": {
           "PreToolUse": [
             {
               "matcher": "Bash",
               "hooks": [{"type": "command", "command": "./ci/prechecks.sh"}]
             }
           ]
         }
       }

    We ignore ``type`` values we don't support yet (only ``"command"``
    runs today) instead of raising, so future extensions can land without
    churning existing settings files.
    """
    registry = HookRegistry(runner=runner)
    block = settings.get("hooks")
    if not isinstance(block, dict):
        return registry

    for event_name, entries in block.items():
        try:
            event = HookEvent(event_name)
        except ValueError:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = str(entry.get("matcher", "")).strip()
            hooks_list = entry.get("hooks")
            if not isinstance(hooks_list, list):
                continue
            for hook_spec in hooks_list:
                if not isinstance(hook_spec, dict):
                    continue
                raw_type = str(hook_spec.get("type", "command")).strip().lower()
                if raw_type not in {"command", "prompt"}:
                    continue
                hook_type = (
                    HookType.COMMAND if raw_type == "command" else HookType.PROMPT
                )
                if hook_type is HookType.COMMAND:
                    command = str(hook_spec.get("command", "")).strip()
                    if not command:
                        continue
                    prompt = ""
                else:
                    prompt = str(hook_spec.get("prompt", "")).strip()
                    if not prompt:
                        continue
                    command = ""
                timeout = hook_spec.get("timeout_seconds") or hook_spec.get("timeout")
                try:
                    timeout_seconds = int(timeout) if timeout is not None else 30
                except (TypeError, ValueError):
                    timeout_seconds = 30
                env = hook_spec.get("env") if isinstance(hook_spec.get("env"), dict) else {}
                registry.add(
                    HookDefinition(
                        event=event,
                        matcher=matcher,
                        command=command,
                        prompt=prompt,
                        hook_type=hook_type,
                        timeout_seconds=timeout_seconds,
                        shell=str(hook_spec.get("shell") or "bash"),
                        env={str(k): str(v) for k, v in env.items()},
                        id=str(hook_spec.get("id", "")),
                    )
                )
    return registry


__all__ = [
    "HookProcessResult",
    "HookRegistry",
    "load_hook_registry",
]
