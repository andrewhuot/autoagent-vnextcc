"""``/init`` slash command.

Runs :func:`scan_workspace` + :func:`write_memory` on demand so the user
can keep ``AGENTLAB.md`` in sync with the current state of the project.
Supports ``--dry-run`` to preview the detected block without touching the
file, and ``--fresh`` to rewrite the default scaffold (losing any
hand-edited sections outside the sentinels).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.init_scan import (
    render_memory,
    scan_workspace,
    write_memory,
)

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


def build_init_command() -> LocalCommand:
    return LocalCommand(
        name="init",
        description="Scan the workspace and refresh AGENTLAB.md",
        handler=_handle_init,
        source="builtin",
        argument_hint="[--dry-run] [--fresh]",
        when_to_use=(
            "Use after major changes to configs, evals, or skills to "
            "keep the project memory file current."
        ),
        sensitive=True,
    )


def _handle_init(ctx: "SlashContext", *args: str) -> OnDoneResult:
    root = _resolve_root(ctx)
    if root is None:
        return on_done(
            theme.warning("  No workspace root resolved — cannot run /init."),
            display="system",
        )

    dry_run = "--dry-run" in args
    fresh = "--fresh" in args
    summary = scan_workspace(root)

    if dry_run:
        preview = render_memory(summary)
        return on_done(
            "\n".join(
                [
                    theme.workspace("/init dry-run — AGENTLAB.md preview"),
                    "",
                    preview,
                ]
            ),
            display="user",
        )

    path = write_memory(summary, preserve_existing=not fresh)
    verb = "Rewrote" if fresh else "Updated"
    body = [
        theme.success(f"  {verb} {path.relative_to(root) if path.is_relative_to(root) else path}."),
        theme.meta(
            "  Scan results:"
            f"  configs={len(summary.agent_configs)}"
            f"  agents={len(summary.agent_sources)}"
            f"  evals={len(summary.eval_cases)}"
            f"  skills={len(summary.user_skills)}"
            f"  plans={len(summary.plans)}"
        ),
    ]
    if summary.is_empty():
        body.append(
            theme.warning(
                "  Scan found nothing — confirm you're in an agentlab workspace."
            )
        )
    return on_done("\n".join(body), display="user")


def _resolve_root(ctx: "SlashContext") -> Path | None:
    workspace = getattr(ctx, "workspace", None)
    root = getattr(workspace, "root", None) if workspace is not None else None
    if root:
        return Path(root)
    override = ctx.meta.get("workspace_root") if ctx.meta else None
    if override:
        return Path(override)
    return None


__all__ = ["build_init_command"]
