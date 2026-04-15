"""Context-window usage visualisation.

Claude Code's ``/context`` renders a colored grid where rows = message roles
and columns = tokens, so the user can see at a glance how much of the
context budget each class of content is consuming. We port the same
primitive in terminal-friendly form:

* Pure function :func:`render_context_grid` builds a list of lines from a
  :class:`ContextSnapshot` — no IO, no side effects, easy to unit test.
* A :class:`Tokenizer` protocol lets callers plug in a real tokenizer
  (tiktoken, Anthropic's counter) while the default
  :func:`approximate_token_count` uses the ``chars / 4`` heuristic so the
  module stays dependency-free and always works offline.

The grid itself is 10 rows × ``width`` columns of Unicode block characters,
coloured per-role via :mod:`cli.workbench_app.theme`. Each cell represents
``context_limit / (rows * width)`` tokens so the footprint of any role is
visible at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Protocol


DEFAULT_CONTEXT_LIMIT = 200_000
"""Mirrors Claude 4.x defaults. Callers with a tighter/looser window should
pass ``context_limit`` through :class:`ContextSnapshot` — the grid scales."""

DEFAULT_WARNING_RATIO = 0.80
"""Ratio at which the grid footer flips to a red-zone warning."""

DEFAULT_GRID_ROWS = 4
DEFAULT_GRID_WIDTH = 40
"""Terminal-friendly default: 4 × 40 = 160 cells, easily visible in a
standard 80-column terminal without line wrapping."""


ROLES_IN_ORDER: tuple[str, ...] = ("system", "user", "assistant", "tool")
"""Role ordering used across the renderer. ``"tool"`` subsumes both the
``tool_use`` and ``tool_result`` block types so the grid stays compact —
most users don't need the two bucketed separately."""


class Tokenizer(Protocol):
    """Pluggable tokeniser. Returns the approximate token count for ``text``."""

    def __call__(self, text: str) -> int:  # pragma: no cover - protocol
        ...


def approximate_token_count(text: str) -> int:
    """Fast, dependency-free token estimator.

    The ratio ``chars ÷ 4`` is the commonly-cited heuristic for Claude and
    GPT-family tokenisers on English text — good enough for a usage grid,
    which is a relative-proportion visualisation, not a billing figure."""
    return max(1, (len(text) + 3) // 4) if text else 0


@dataclass
class ContextSnapshot:
    """Aggregated token counts for one transcript.

    Built from the :class:`~cli.sessions.Session.transcript` plus any
    system-prompt / tool-schema text the caller wants to attribute. We keep
    the shape intentionally flat (dict of role → int) so callers that can't
    enumerate every message still get a useful grid.
    """

    role_tokens: dict[str, int] = field(default_factory=dict)
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    warning_ratio: float = DEFAULT_WARNING_RATIO

    @property
    def total_tokens(self) -> int:
        return sum(self.role_tokens.values())

    @property
    def used_ratio(self) -> float:
        return min(1.0, self.total_tokens / self.context_limit) if self.context_limit else 0.0

    @property
    def warning(self) -> bool:
        return self.used_ratio >= self.warning_ratio


def snapshot_from_transcript(
    transcript: Iterable[Mapping[str, str]],
    *,
    tokenizer: Tokenizer = approximate_token_count,
    system_prompt: str = "",
    tool_overhead: int = 0,
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
    warning_ratio: float = DEFAULT_WARNING_RATIO,
    model: str | None = None,
) -> ContextSnapshot:
    """Build a :class:`ContextSnapshot` from a sequence of role/content dicts.

    Accepts the :class:`cli.sessions.SessionEntry` wire format (``role``
    and ``content`` keys) so callers that already persist transcripts don't
    need an adapter. ``tool_overhead`` accounts for schema definitions the
    model sees but the transcript doesn't store verbatim.

    ``model`` is an optional canonical model id. When supplied *and* the
    caller kept the default ``context_limit``, we look the window up in
    :mod:`cli.llm.capabilities` so GPT-5/Gemini sessions report their full
    1M window instead of the 200k Claude fallback. An explicit
    ``context_limit`` always wins — adapters that already know the true
    limit shouldn't be second-guessed."""
    role_tokens: dict[str, int] = {role: 0 for role in ROLES_IN_ORDER}
    if system_prompt:
        role_tokens["system"] += tokenizer(system_prompt)
    if tool_overhead:
        role_tokens["tool"] += max(0, int(tool_overhead))

    for entry in transcript:
        role = _normalize_role(entry.get("role", "user"))
        content = str(entry.get("content", ""))
        role_tokens[role] += tokenizer(content)

    resolved_limit = context_limit
    if model and context_limit == DEFAULT_CONTEXT_LIMIT:
        # Lazy import keeps this module dependency-free for callers that
        # never reach this branch (e.g. tests that pass an explicit limit).
        from cli.llm.capabilities import resolve_context_limit

        resolved_limit = resolve_context_limit(model, default=DEFAULT_CONTEXT_LIMIT)

    return ContextSnapshot(
        role_tokens=role_tokens,
        context_limit=resolved_limit,
        warning_ratio=warning_ratio,
    )


def render_context_grid(
    snapshot: ContextSnapshot,
    *,
    rows: int = DEFAULT_GRID_ROWS,
    width: int = DEFAULT_GRID_WIDTH,
    color: bool = True,
    role_labels: Mapping[str, str] | None = None,
    styler: Callable[[str, str], str] | None = None,
) -> list[str]:
    """Return the grid + summary as printable lines.

    The grid is a single ``rows`` × ``width`` block where each cell is
    tinted by the role that owns the largest share of that slot. This
    mirrors Claude Code's visualisation: readers can eyeball which role is
    dominating the window without parsing numbers.

    ``styler`` lets tests capture style calls without spinning up the real
    theme helpers; production callers pass ``None`` to use the default."""
    labels = dict(role_labels or _DEFAULT_ROLE_LABELS)
    total_cells = rows * width
    cells_per_role = _allocate_cells(snapshot, total_cells)
    sequence = _expand_role_sequence(cells_per_role)

    styler = styler if styler is not None else (_themed_styler if color else _raw_styler)
    grid_rows = []
    for row_index in range(rows):
        segment = sequence[row_index * width : (row_index + 1) * width]
        rendered = "".join(styler(role, _CELL_CHAR) for role in segment)
        grid_rows.append("  " + rendered)

    summary: list[str] = []
    summary.append(
        f"  Context window: {snapshot.total_tokens:,} / "
        f"{snapshot.context_limit:,} tokens "
        f"({snapshot.used_ratio * 100:.1f}%)"
    )
    if snapshot.warning:
        summary.append(
            styler("warning", "  Warning: context usage above "
                  f"{int(snapshot.warning_ratio * 100)}% — consider /compact")
        )

    legend_parts = []
    for role in ROLES_IN_ORDER:
        tokens = snapshot.role_tokens.get(role, 0)
        if not tokens:
            continue
        pct = (tokens / snapshot.total_tokens * 100) if snapshot.total_tokens else 0.0
        legend_parts.append(
            f"{styler(role, '■')} {labels.get(role, role)} "
            f"{tokens:,} ({pct:.1f}%)"
        )
    legend_line = "  " + "   ".join(legend_parts) if legend_parts else "  (empty context)"

    return [*grid_rows, legend_line, *summary]


# ---------------------------------------------------------------------------
# Allocation helpers
# ---------------------------------------------------------------------------


def _allocate_cells(snapshot: ContextSnapshot, total_cells: int) -> dict[str, int]:
    """Distribute ``total_cells`` across roles proportional to token counts.

    Claude Code fills the grid left-to-right in role order, padding the
    trailing cells with "unused" slots (dim background) when the window
    isn't full. We mirror that: any leftover capacity lands in a pseudo
    role ``"free"`` so the legend stays accurate."""
    allocations: dict[str, int] = {role: 0 for role in (*ROLES_IN_ORDER, "free")}
    if snapshot.context_limit <= 0 or total_cells <= 0:
        return allocations

    used_cells = 0
    for role in ROLES_IN_ORDER:
        tokens = snapshot.role_tokens.get(role, 0)
        if tokens <= 0:
            continue
        cells = (tokens * total_cells) // snapshot.context_limit
        allocations[role] = cells
        used_cells += cells

    if used_cells > total_cells:
        # Rounding can occasionally push us over — trim the largest role.
        overflow = used_cells - total_cells
        largest_role = max(ROLES_IN_ORDER, key=lambda r: allocations[r])
        allocations[largest_role] = max(0, allocations[largest_role] - overflow)
        used_cells = sum(allocations[role] for role in ROLES_IN_ORDER)

    allocations["free"] = max(0, total_cells - used_cells)
    return allocations


def _expand_role_sequence(cells_per_role: Mapping[str, int]) -> list[str]:
    sequence: list[str] = []
    for role in (*ROLES_IN_ORDER, "free"):
        sequence.extend([role] * cells_per_role.get(role, 0))
    return sequence


# ---------------------------------------------------------------------------
# Stylers
# ---------------------------------------------------------------------------


_CELL_CHAR = "█"
_DEFAULT_ROLE_LABELS: dict[str, str] = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tools",
    "free": "free",
}


def _raw_styler(role: str, text: str) -> str:
    return text


def _themed_styler(role: str, text: str) -> str:
    """Wrap ``text`` in the role's theme colour.

    Imported lazily so unit tests that only need the layout can skip the
    terminal dependency entirely."""
    from cli.workbench_app import theme

    return _THEME_FOR_ROLE.get(role, theme.meta)(text)


def _normalize_role(raw: str) -> str:
    raw = (raw or "").lower().strip()
    if raw in ROLES_IN_ORDER:
        return raw
    if raw in {"tool_use", "tool_result", "tools"}:
        return "tool"
    if raw == "human":
        return "user"
    return "user"


# Populated lazily in :func:`_themed_styler` to avoid importing theme at
# module load (keeps ``tests/test_context_viz.py`` import-free of click).
_THEME_FOR_ROLE: dict[str, Callable[[str], str]] = {}


def _install_theme_map() -> None:
    from cli.workbench_app import theme

    _THEME_FOR_ROLE.update(
        {
            "system": theme.meta,
            "user": theme.workspace,
            "assistant": theme.success,
            "tool": theme.warning,
            "free": theme.meta,
            "warning": theme.warning,
        }
    )


_install_theme_map()
