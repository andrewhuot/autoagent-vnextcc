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
from cli.workbench_app.effort import (
    EffortIndicator,
    EffortSnapshot,
    format_effort,
    format_elapsed,
)
from cli.workbench_app.output_collapse import (
    CollapsibleOutput,
    format_summary,
)
from cli.workbench_app.slash import (
    DispatchResult,
    SlashContext,
    build_builtin_registry,
    dispatch,
    parse_slash_line,
)
from cli.workbench_app.status_bar import (
    StatusBar,
    StatusSnapshot,
    render_snapshot,
    snapshot_from_workspace,
)
from cli.workbench_app.transcript import (
    Transcript,
    TranscriptEntry,
    TranscriptRole,
    format_entry,
)

__all__ = [
    "CollapsibleOutput",
    "CommandContext",
    "CommandEffort",
    "CommandRegistry",
    "CommandSource",
    "DEFAULT_PROMPT",
    "DispatchResult",
    "EffortIndicator",
    "EffortSnapshot",
    "LocalCommand",
    "LocalJSXCommand",
    "PromptCommand",
    "SlashCommand",
    "SlashCommandKind",
    "SlashContext",
    "StatusBar",
    "StatusSnapshot",
    "StubAppResult",
    "Transcript",
    "TranscriptEntry",
    "TranscriptRole",
    "build_builtin_registry",
    "build_status_line",
    "dispatch",
    "format_effort",
    "format_elapsed",
    "format_entry",
    "format_summary",
    "parse_slash_line",
    "render_snapshot",
    "run_workbench_app",
    "snapshot_from_workspace",
]
