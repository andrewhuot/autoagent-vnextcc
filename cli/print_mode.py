"""Non-interactive ``agentlab print`` entry point.

Mirrors Claude Code's ``claude -p "prompt"`` UX: runs one orchestrator
turn in headless mode and emits the result to stdout. JSON and plain
modes are both supported so callers can pipe the output.

The command is a thin adapter around :class:`cli.llm.LLMOrchestrator`:

* Resolves the workspace (fails fast when absent — print mode without a
  workspace has no meaningful context).
* Builds the tool registry, permission manager, and hook registry the
  same way the REPL does at startup.
* Requires the caller to inject a :class:`ModelClient` — we intentionally
  do *not* default to a provider, because the provider choice depends on
  configured credentials and is better made by the caller (or a future
  factory in :mod:`adapters`).

A stub model is supplied for tests so CI can exercise the full command
path without API keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import click

from cli.errors import click_error
from cli.hooks import HookRegistry, load_hook_registry
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelClient,
    ModelResponse,
)
from cli.permissions import PermissionManager, load_workspace_settings
from cli.sessions import SessionStore
from cli.tools.registry import default_registry
from cli.workbench_app.output_style import OutputStyle


ModelFactory = Callable[[str], ModelClient]
"""Takes the resolved system prompt and returns a :class:`ModelClient`.

Kept as a callable so tests inject a stub without patching provider
adapters, and so future providers can plug in via a single seam."""


@dataclass
class PrintResult:
    """Machine-readable summary of a print run."""

    text: str
    stop_reason: str
    tool_calls: int
    usage: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "stop_reason": self.stop_reason,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
        }


def run_print(
    prompt: str,
    *,
    workspace_root: Path,
    model_factory: ModelFactory,
    output_style: OutputStyle = OutputStyle.CONCISE,
    system_prompt: str = "",
    echo: Callable[[str], None] = click.echo,
) -> PrintResult:
    """Execute one non-interactive turn and return its summary.

    Runs the same orchestrator the REPL uses, but:

    * Uses a noop dialog runner that *denies* anything requiring
      interactive approval — headless sessions must preconfigure
      permissions via settings.json rather than rely on user prompts.
    * Skips transcript checkpointing; print-mode runs are
      conceptually one-shot and the transcript-checkpoint surface
      doesn't add value.
    * Forwards the orchestrator's streamed output through ``echo`` only
      when the style is ``concise`` or ``verbose``. ``json`` mode
      suppresses streaming so stdout carries exactly one JSON object.
    """
    if not prompt.strip():
        raise click_error("agentlab print requires a non-empty prompt.")

    permission_manager = PermissionManager(root=workspace_root)
    settings = load_workspace_settings(workspace_root)
    hook_registry = load_hook_registry(settings)
    tool_registry = default_registry()

    # Session store is optional for print mode but giving the orchestrator
    # an ephemeral session lets tools that need a session_id (e.g. skill
    # dispatch in future phases) keep working.
    session_store = SessionStore(workspace_dir=workspace_root)
    session = session_store.create(title=f"print: {prompt[:60]}")

    model = model_factory(system_prompt)

    def deny_dialog(*_args, **_kwargs):
        from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome

        return DialogOutcome(
            choice=DialogChoice.DENY,
            allow=False,
            persist_rule=None,
            persist_scope=None,
        )

    streaming_echo = echo if output_style is not OutputStyle.JSON else (lambda _line: None)

    orchestrator = LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=permission_manager,
        workspace_root=workspace_root,
        session=session,
        session_store=session_store,
        hook_registry=hook_registry,
        system_prompt=system_prompt,
        dialog_runner=deny_dialog,
        echo=streaming_echo,
    )

    result = orchestrator.run_turn(prompt)

    summary = PrintResult(
        text=result.assistant_text,
        stop_reason=result.stop_reason,
        tool_calls=len(result.tool_executions),
        usage=result.usage,
    )

    if output_style is OutputStyle.JSON:
        echo(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    elif output_style is OutputStyle.VERBOSE:
        echo("")
        echo(f"[stop_reason={summary.stop_reason} tool_calls={summary.tool_calls}]")
        if summary.usage:
            echo(f"[usage={summary.usage}]")

    return summary


# ---------------------------------------------------------------------------
# Click command (mounted in runner.py)
# ---------------------------------------------------------------------------


def _default_model_factory(system_prompt: str) -> ModelClient:
    """Placeholder model factory used when the caller doesn't supply one.

    Returns an ``EchoModel`` that simply parrots the prompt — this keeps
    ``agentlab print`` exercisable without credentials and gives the
    tests a predictable fixture. Real adapters plug in at the call site
    via ``--model-factory`` (future work)."""
    return EchoModel()


class EchoModel:
    """Trivial :class:`ModelClient` for smoke tests and demos.

    Emits a single text block echoing the last user message, flagged
    with ``stop_reason="end_turn"``. Does not call any tools."""

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        del system_prompt, tools
        last = messages[-1] if messages else None
        text = getattr(last, "content", "") if last is not None else ""
        return ModelResponse(
            blocks=[AssistantTextBlock(text=f"echo: {text}")],
            stop_reason="end_turn",
        )


@click.command("print")
@click.argument("prompt", required=True)
@click.option(
    "--style",
    type=click.Choice([s.value for s in OutputStyle], case_sensitive=False),
    default=OutputStyle.CONCISE.value,
    show_default=True,
    help="Output verbosity: concise / verbose / json.",
)
@click.option(
    "--system-prompt",
    default="",
    show_default=False,
    help="Optional system prompt forwarded to the model.",
)
def print_command(prompt: str, style: str, system_prompt: str) -> None:
    """Run a single non-interactive turn and print the result."""
    from cli.workspace import discover_workspace

    workspace = discover_workspace()
    if workspace is None:
        raise click_error(
            "agentlab print requires an initialised workspace. Run "
            "`agentlab new` or `cd` into one."
        )
    workspace_root = Path(workspace.root)

    run_print(
        prompt=prompt,
        workspace_root=workspace_root,
        model_factory=_default_model_factory,
        output_style=OutputStyle(style.lower()),
        system_prompt=system_prompt,
    )


__all__ = [
    "EchoModel",
    "ModelFactory",
    "PrintResult",
    "print_command",
    "run_print",
]
