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

from pydantic import ValidationError

from cli.hooks.types import (
    HookDefinition,
    HookEvent,
    HookOutcome,
    HookType,
    HookVerdict,
)
from cli.settings import Settings


Runner = Callable[[HookDefinition, dict[str, Any]], "HookProcessResult"]

_EVENT_ALIASES = {
    "beforeTool": "PreToolUse",
    "afterTool": "PostToolUse",
}
_GATING_EVENTS = {
    HookEvent.BEFORE_QUERY,
    HookEvent.PRE_TOOL_USE,
    HookEvent.ON_PERMISSION_REQUEST,
}


@dataclass(frozen=True)
class _ParsedHookOutput:
    """Protocol details extracted from hook stdout, if stdout is JSON."""

    verdict: HookVerdict | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    consumed_stdout: bool = False


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

    @classmethod
    def load_from_settings(
        cls,
        settings: Settings,
        runner: Runner | None = None,
    ) -> "HookRegistry":
        """Build a registry from typed settings so runtime loading shares schema defaults."""
        registry = cls(runner=runner)
        hooks = settings.hooks
        default_timeout = hooks.timeout_seconds
        for event_name, entries in hooks.event_map().items():
            _load_event_entries(
                registry,
                event_name,
                entries,
                default_timeout_seconds=default_timeout,
            )
        return registry

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
        gating = event in _GATING_EVENTS
        payload_dict = dict(payload or {})

        for hook in hooks:
            result = runner(hook, payload_dict)
            outcome.record_fired()
            if result.timed_out:
                outcome.record_timeout(
                    f"Hook {hook.command!r} timed out after {hook.timeout_seconds}s."
                )
                if gating:
                    break
                continue

            parsed = _parse_json_stdout(result.stdout)
            if parsed.metadata:
                outcome.metadata.update(parsed.metadata)
            message = _message_from_result(result, parsed)

            if result.returncode != 0:
                outcome.record_deny(message or f"Hook exited {result.returncode}")
                if gating:
                    break
                continue

            if parsed.verdict is HookVerdict.DENY:
                outcome.record_deny(message)
                if gating:
                    break
            elif parsed.verdict is HookVerdict.ASK:
                outcome.record_ask(message)
            else:
                if message:
                    outcome.record_inform(message)

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
    settings: Settings | Mapping[str, Any],
    *,
    runner: Runner | None = None,
) -> HookRegistry:
    """Compatibility wrapper accepting typed settings or legacy raw mappings.

    New runtime code should call :meth:`HookRegistry.load_from_settings` with a
    typed :class:`~cli.settings.Settings`. Older call sites and tests still pass
    a parsed ``settings.json`` dict, so this wrapper keeps that shape working:

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

    We ignore event or hook ``type`` values we don't support instead of raising,
    so future settings can land without breaking existing workspaces.
    """
    if isinstance(settings, Settings):
        return HookRegistry.load_from_settings(settings, runner=runner)

    try:
        typed_settings = Settings.model_validate(settings)
    except (TypeError, ValidationError, ValueError):
        return _load_from_raw_mapping(settings, runner=runner)

    return HookRegistry.load_from_settings(typed_settings, runner=runner)


def _load_from_raw_mapping(
    settings: Mapping[str, Any],
    *,
    runner: Runner | None = None,
) -> HookRegistry:
    """Best-effort loader for raw mappings that do not pass the strict schema."""
    registry = HookRegistry(runner=runner)
    block = settings.get("hooks")
    if not isinstance(block, dict):
        return registry

    default_timeout = _coerce_timeout(block.get("timeout_seconds"), 5)

    for event_name, entries in block.items():
        if event_name == "timeout_seconds":
            continue
        _load_event_entries(
            registry,
            str(event_name),
            entries,
            default_timeout_seconds=default_timeout,
        )
    return registry


def _load_event_entries(
    registry: HookRegistry,
    event_name: str,
    entries: Any,
    *,
    default_timeout_seconds: int,
) -> None:
    """Parse one event bucket from either Pydantic models or raw mappings."""
    event = _event_from_name(event_name)
    if event is None or not isinstance(entries, list):
        return

    for entry in entries:
        matcher = str(_read_field(entry, "matcher", "") or "").strip()
        hooks_list = _read_field(entry, "hooks", [])
        if not isinstance(hooks_list, list):
            continue
        for hook_spec in hooks_list:
            definition = _definition_from_spec(
                event,
                matcher,
                hook_spec,
                default_timeout_seconds=default_timeout_seconds,
            )
            if definition is not None:
                registry.add(definition)


def _definition_from_spec(
    event: HookEvent,
    matcher: str,
    hook_spec: Any,
    *,
    default_timeout_seconds: int,
) -> HookDefinition | None:
    raw_type = str(_read_field(hook_spec, "type", "command") or "command").strip().lower()
    if raw_type not in {"command", "prompt"}:
        return None

    hook_type = HookType.COMMAND if raw_type == "command" else HookType.PROMPT
    if hook_type is HookType.COMMAND:
        command = str(_read_field(hook_spec, "command", "") or "").strip()
        if not command:
            return None
        prompt = ""
    else:
        prompt = str(_read_field(hook_spec, "prompt", "") or "").strip()
        if not prompt:
            return None
        command = ""

    timeout = _read_field(hook_spec, "timeout_seconds", None)
    if timeout is None:
        timeout = _read_field(hook_spec, "timeout", None)
    env = _read_field(hook_spec, "env", {})
    if not isinstance(env, dict):
        env = {}

    return HookDefinition(
        event=event,
        matcher=matcher,
        command=command,
        prompt=prompt,
        hook_type=hook_type,
        timeout_seconds=_coerce_timeout(timeout, default_timeout_seconds),
        shell=str(_read_field(hook_spec, "shell", "bash") or "bash"),
        env={str(k): str(v) for k, v in env.items()},
        id=str(_read_field(hook_spec, "id", "") or ""),
    )


def _event_from_name(event_name: str) -> HookEvent | None:
    canonical = _EVENT_ALIASES.get(event_name, event_name)
    try:
        return HookEvent(canonical)
    except ValueError:
        return None


def _read_field(source: Any, field_name: str, default: Any) -> Any:
    if isinstance(source, Mapping):
        return source.get(field_name, default)
    return getattr(source, field_name, default)


def _coerce_timeout(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None else int(default)
    except (TypeError, ValueError):
        return int(default)


def _parse_json_stdout(stdout: str) -> _ParsedHookOutput:
    stripped = stdout.strip()
    if not stripped:
        return _ParsedHookOutput()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return _ParsedHookOutput()
    if not isinstance(payload, dict):
        return _ParsedHookOutput()

    metadata: dict[str, Any] = {}
    decision = payload.get("decision")
    reason = payload.get("reason")
    hook_specific = payload.get("hookSpecificOutput")
    if isinstance(hook_specific, dict):
        decision = hook_specific.get("permissionDecision", decision)
        reason = hook_specific.get("permissionDecisionReason", reason)
        if "updatedMCPToolOutput" in hook_specific:
            metadata["updated_mcp_tool_output"] = hook_specific[
                "updatedMCPToolOutput"
            ]

    verdict = _verdict_from_decision(decision)
    consumed_stdout = verdict is not None or bool(metadata)
    return _ParsedHookOutput(
        verdict=verdict,
        message=str(reason).strip() if reason is not None else "",
        metadata=metadata,
        consumed_stdout=consumed_stdout,
    )


def _verdict_from_decision(decision: Any) -> HookVerdict | None:
    normalized = str(decision or "").strip().lower()
    if normalized == "allow":
        return HookVerdict.ALLOW
    if normalized == "ask":
        return HookVerdict.ASK
    if normalized == "deny":
        return HookVerdict.DENY
    return None


def _message_from_result(
    result: HookProcessResult,
    parsed: _ParsedHookOutput,
) -> str:
    if parsed.message:
        return parsed.message
    stderr = result.stderr.strip()
    if stderr:
        return stderr
    if parsed.consumed_stdout:
        return ""
    return result.stdout.strip()


__all__ = [
    "HookProcessResult",
    "HookRegistry",
    "load_hook_registry",
]
