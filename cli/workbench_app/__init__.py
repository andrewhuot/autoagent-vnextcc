"""Interactive workbench application (Claude-Code-style REPL).

Modules are imported lazily by the entry point to keep startup cost low. The
command taxonomy in ``commands`` is the canonical registration surface; all
slash commands register through it.
"""

from cli.workbench_app.app import (
    DEFAULT_PROMPT,
    StubAppResult,
    build_status_line,
    run_workbench_app,
)
from cli.workbench_app.commands import (
    CommandContext,
    CommandEffort,
    CommandRegistry,
    CommandSource,
    LocalCommand,
    LocalJSXCommand,
    PromptCommand,
    SlashCommand,
    SlashCommandKind,
)

__all__ = [
    "CommandContext",
    "CommandEffort",
    "CommandRegistry",
    "CommandSource",
    "DEFAULT_PROMPT",
    "LocalCommand",
    "LocalJSXCommand",
    "PromptCommand",
    "SlashCommand",
    "SlashCommandKind",
    "StubAppResult",
    "build_status_line",
    "run_workbench_app",
]
