"""Streaming markdown renderer for the workbench transcript.

Claude Code renders the model's reply token-by-token with live code-fence
styling, diff highlighting, and smooth reflow. A full Ink-style render is
out of scope for the Phase-3 port — the CLI uses ``click.echo`` / prompt
toolkit lines, not a refreshing TUI — but the stream still benefits from
two targeted behaviours:

* **Line-anchored emission** — the renderer buffers partial content until
  a newline arrives, then emits the completed line with the styling that
  its mode implies (code fence / diff block / plain paragraph).
* **Mode tracking** — as the stream arrives we track whether we're inside
  a fenced code block and whether the block is a diff (``diff`` language
  tag *or* lines that start with ``+``/``-``). Code fences stay coloured
  consistently across chunk boundaries and the closing fence marker is
  handled correctly even when it arrives mid-chunk.

The module is self-contained: no prompt_toolkit import, no dependency on
:mod:`rich`. That keeps the test harness fast and makes the streamer usable
from any LLM adapter — the adapter calls :meth:`StreamingMarkdownRenderer.feed`
with each chunk and :meth:`finalize` at end of stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, get_args

from cli.workbench_app.output_style import STYLES, apply_style, parse_style_directive


EchoFn = Callable[[str], None]
_STYLE_DIRECTIVES = tuple(f'<agentlab output-style="{style}">' for style in get_args(STYLES))


class BlockMode(str, Enum):
    """Current segment of the stream."""

    PROSE = "prose"
    CODE = "code"
    DIFF = "diff"


@dataclass
class RenderedLine:
    """One emitted line plus the mode that styled it. Used by tests and
    callers that want to re-style after the fact (e.g. a future TUI)."""

    text: str
    mode: BlockMode
    fence_language: str = ""


@dataclass
class StreamingMarkdownRenderer:
    """Incrementally format streaming markdown output.

    Usage::

        renderer = StreamingMarkdownRenderer(echo=print)
        for chunk in stream:
            renderer.feed(chunk)
        renderer.finalize()

    :meth:`feed` emits every *complete* line it can extract from the buffer
    so partial lines never render twice. :meth:`finalize` flushes whatever
    remains in the buffer, styled with the mode that was active when the
    stream ended — important because the model might end on a trailing
    partial line without a newline."""

    echo: EchoFn
    styler: Callable[[str, BlockMode, str], str] | None = None
    """Optional override for the default theme-based styler — tests inject
    a lambda that tags each line so assertions can inspect modes without
    parsing ANSI codes."""

    buffer: str = ""
    mode: BlockMode = BlockMode.PROSE
    fence_language: str = ""
    emitted: list[RenderedLine] = field(default_factory=list)
    directive_checked: bool = False
    directive_style: str | None = None

    def feed(self, chunk: str) -> None:
        """Append ``chunk`` to the buffer and emit every complete line.

        Empty chunks are a no-op so adapters can forward heartbeats
        without guarding. Newlines inside the chunk are honoured; CRLF is
        normalised to LF so the stream looks the same regardless of the
        adapter's host OS."""
        if not chunk:
            return
        self.buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
        if not self.directive_checked:
            if self._maybe_parse_style_directive():
                return
        if self.directive_style is not None:
            return
        self._emit_available_lines()

    def finalize(self) -> None:
        """Flush any residual partial line at end of stream."""
        if not self.directive_checked:
            self._maybe_parse_style_directive(final=True)
        if self.directive_style is not None:
            styled_text = apply_style(self.buffer.removesuffix("\n"), self.directive_style)
            self.buffer = ""
            self._emit_complete_text(styled_text)
            return
        if self.buffer:
            self._emit_line(self.buffer)
            self.buffer = ""

    # ------------------------------------------------------------------ internal

    def _maybe_parse_style_directive(self, *, final: bool = False) -> bool:
        """Probe the very start of the stream for an output-style directive.

        Returns ``True`` when the renderer must keep buffering because the
        prefix is still ambiguous or because a directive was successfully
        detected and the styled payload should wait until :meth:`finalize`.
        """
        stripped, style = parse_style_directive(self.buffer)
        if style is not None:
            self.directive_checked = True
            self.directive_style = style
            self.buffer = stripped
            return True
        if not final and _is_possible_style_directive_prefix(self.buffer):
            return True
        self.directive_checked = True
        return False

    def _emit_available_lines(self) -> None:
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._emit_line(line)

    def _emit_complete_text(self, text: str) -> None:
        remaining = text
        while "\n" in remaining:
            line, remaining = remaining.split("\n", 1)
            self._emit_line(line)
        if remaining:
            self._emit_line(remaining)

    def _emit_line(self, raw_line: str) -> None:
        line = raw_line.rstrip("\r")
        fence = _match_fence(line)
        if fence is not None:
            # Opening or closing fence: the fence line itself renders in
            # the surrounding mode (prose) so it always reads as a
            # delimiter rather than a payload.
            self._emit_styled(line, BlockMode.PROSE, fence_language=fence or self.fence_language)
            if self.mode == BlockMode.PROSE:
                self.fence_language = fence
                self.mode = BlockMode.DIFF if _is_diff_language(fence) else BlockMode.CODE
            else:
                self.mode = BlockMode.PROSE
                self.fence_language = ""
            return

        effective_mode = self.mode
        if effective_mode == BlockMode.CODE and _looks_like_diff_line(line):
            # A ``` block labelled as a neutral language (e.g. ``py``)
            # can still contain diff-like markers — we upgrade per-line
            # to keep the diff colouring correct without forcing callers
            # to annotate their fences.
            effective_mode = BlockMode.DIFF

        if effective_mode == BlockMode.PROSE and _looks_like_diff_line(line):
            # Standalone diff markers outside a fence (e.g. a commit
            # message quoting a hunk) also benefit from diff styling.
            effective_mode = BlockMode.DIFF

        self._emit_styled(line, effective_mode, fence_language=self.fence_language)

    def _emit_styled(self, line: str, mode: BlockMode, *, fence_language: str) -> None:
        styler = self.styler or _themed_styler
        rendered = styler(line, mode, fence_language)
        self.echo(rendered)
        self.emitted.append(RenderedLine(text=line, mode=mode, fence_language=fence_language))


# ---------------------------------------------------------------------------
# Convenience: batch rendering for non-streaming callers
# ---------------------------------------------------------------------------


def render_markdown_lines(
    text: str,
    *,
    styler: Callable[[str, BlockMode, str], str] | None = None,
) -> list[str]:
    """Return fully styled lines for a complete markdown string.

    Handy for non-streaming paths that still want the same highlighting
    behaviour — e.g. :mod:`cli.workbench_app.screens.plan` could route
    plan bodies through this helper in a future revision."""
    rendered: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=rendered.append, styler=styler)
    renderer.feed(text if text.endswith("\n") else text + "\n")
    renderer.finalize()
    return rendered


# ---------------------------------------------------------------------------
# Fence & diff detection helpers
# ---------------------------------------------------------------------------


def _match_fence(line: str) -> str | None:
    """Return the fence language when ``line`` opens/closes a fence.

    ``None`` when the line is not a fence marker. A bare ```` ``` `` returns
    an empty string so the caller can distinguish "closing fence" (empty
    tag) from "not a fence"."""
    stripped = line.lstrip()
    if not stripped.startswith("```"):
        return None
    return stripped[3:].strip().lower()


def _is_diff_language(fence_language: str) -> bool:
    return fence_language in {"diff", "patch"}


def _looks_like_diff_line(line: str) -> bool:
    """Heuristic: a line that starts with ``+`` or ``-`` (but not ``+++``,
    ``---``, ``-- ``, etc.) reads as a diff marker. We intentionally skip
    lone ``+``/``-`` on empty lines since those are common in prose."""
    if len(line) < 2:
        return False
    head, rest = line[0], line[1:]
    if head not in "+-":
        return False
    if rest.startswith(head):  # "+++" / "---" are hunk headers — still diff.
        return True
    if rest.startswith(" "):
        return True
    return False


def _is_possible_style_directive_prefix(text: str) -> bool:
    return any(directive.startswith(text) for directive in _STYLE_DIRECTIVES)


# ---------------------------------------------------------------------------
# Theming
# ---------------------------------------------------------------------------


def _themed_styler(line: str, mode: BlockMode, fence_language: str) -> str:
    """Default line styler: delegates to :mod:`cli.workbench_app.theme`.

    Imported lazily so callers that only need the plain text (test
    assertions, JSON output modes) can bypass the click/terminal stack."""
    from cli.workbench_app import theme

    if mode == BlockMode.CODE:
        return theme.meta(line)
    if mode == BlockMode.DIFF:
        if line.startswith("+") and not line.startswith("+++"):
            return theme.success(line)
        if line.startswith("-") and not line.startswith("---"):
            return theme.warning(line)
        return theme.meta(line)
    # Prose with a leading fence keeps the fence itself muted so it reads
    # as a delimiter rather than content.
    if line.lstrip().startswith("```"):
        return theme.meta(line)
    return line


def iter_styled_lines(
    chunks: Iterable[str],
    *,
    styler: Callable[[str, BlockMode, str], str] | None = None,
) -> Iterable[str]:
    """Yield styled lines for an iterable of chunks.

    Convenience wrapper for async-less consumers that already have the
    full iterator in memory but still want the streaming behaviour."""
    collected: list[str] = []
    renderer = StreamingMarkdownRenderer(echo=collected.append, styler=styler)
    for chunk in chunks:
        renderer.feed(chunk)
    renderer.finalize()
    yield from collected


__all__ = [
    "BlockMode",
    "RenderedLine",
    "StreamingMarkdownRenderer",
    "iter_styled_lines",
    "render_markdown_lines",
]
