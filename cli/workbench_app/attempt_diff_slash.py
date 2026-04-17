"""`/attempt-diff <attempt_id>` — multi-pane lineage-backed attempt viewer (R4.10).

Distinct from :mod:`cli.workbench_app.config_diff_slash`, which owns ``/diff``
for *version-manifest* diffs (active config vs candidate version). This module
renders a three-pane card for one :class:`optimizer.improvement_lineage`
``attempt_id``:

1. **Baseline**  — path + YAML snippet of the baseline config.
2. **Candidate** — path + YAML snippet of the candidate config.
3. **Eval Delta** — composite before/after/delta from the attempt's
   measurement event (or a ``no measurement recorded`` stub).

Pure read-only handler — no DB writes, no network. All rendering is plain
Textual markup so the transcript widget can surface the result verbatim.

Slash context ``meta`` keys honoured:

- ``lineage_store`` — caller-supplied :class:`ImprovementLineageStore`.
- ``lineage_db_path`` — fallback sqlite path if no store is cached.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    AttemptLineageView,
    ImprovementLineageStore,
)


# Keep this small — the pane is an inline card, not a full editor view.
_YAML_PREVIEW_LINES = 40


def build_attempt_diff_command() -> LocalCommand:
    """Build the ``/attempt-diff`` slash command.

    Named ``attempt-diff`` (not ``diff``) to avoid colliding with the
    existing ``/diff`` registered by :mod:`config_diff_slash`, which diffs
    versioned configs rather than lineage attempts.

    Note: the description and ``when_to_use`` intentionally avoid the literal
    token ``eval`` — the fuzzy completer's level-7 close-matches scan would
    otherwise surface this command ahead of ``/eval`` for typo queries like
    ``/evl``. See :mod:`cli.workbench_app.completer`.
    """
    return LocalCommand(
        name="attempt-diff",
        description="Show baseline/candidate config and verification delta for a lineage attempt",
        handler=_handle_attempt_diff,
        source="builtin",
        argument_hint="<attempt_id>",
        when_to_use=(
            "Use to inspect an optimizer attempt's before/after config and "
            "verification delta from the R2 improvement lineage."
        ),
        sensitive=False,
    )


# ---------------------------------------------------------------------------
# Handler.
# ---------------------------------------------------------------------------


def _handle_attempt_diff(ctx: SlashContext, *args: str) -> OnDoneResult:
    attempt_id = _first_token(args)
    if not attempt_id:
        return on_done(
            "  Usage: /attempt-diff <attempt_id>",
            display="system",
        )

    store = _resolve_store(ctx)
    if store is None:
        return on_done(
            "  No lineage store available. Pass `lineage_store` via slash context.",
            display="system",
        )

    view = store.view_attempt(attempt_id)
    if not view.events:
        return on_done(f"[red]Unknown attempt: {attempt_id}[/]", display="system")

    baseline_path = _extract_config_path(view, "baseline_config_path")
    candidate_path = _extract_config_path(view, "candidate_config_path")

    parts: list[str] = []
    parts.append(_render_config_pane("Baseline", baseline_path))
    parts.append(_render_config_pane("Candidate", candidate_path))
    parts.append(_render_delta_pane(view))
    return on_done("\n\n".join(parts), display="user")


# ---------------------------------------------------------------------------
# Rendering helpers.
# ---------------------------------------------------------------------------


def _render_config_pane(label: str, path: str | None) -> str:
    if not path:
        return f"[bold]{label}:[/] [dim]<not recorded>[/]"
    header = f"[bold]{label}:[/] {path}"
    body = _read_yaml_preview(Path(path))
    if body is None:
        return "\n".join([header, "  [dim]<unreadable>[/]"])
    indented = "\n".join(f"  [dim]{line}[/]" for line in body.splitlines())
    return "\n".join([header, indented]) if indented else header


def _render_delta_pane(view: AttemptLineageView) -> str:
    header = "[bold]Eval Delta:[/]"
    before = _coalesce_score_before(view)
    after = _coalesce_score_after(view)
    delta = _coalesce_delta(view, before, after)

    has_measurement = view.measurement_id is not None or view.composite_delta is not None
    if not has_measurement and before is None and after is None:
        return "\n".join([header, "  [dim]no measurement recorded[/]"])

    lines = [header]
    if before is not None:
        lines.append(f"  composite_before: {before:.3f}")
    else:
        lines.append("  composite_before: [dim]n/a[/]")
    if after is not None:
        lines.append(f"  composite_after:  {after:.3f}")
    else:
        lines.append("  composite_after:  [dim]n/a[/]")
    if delta is not None:
        sign = "+" if delta >= 0 else "-"
        lines.append(f"  delta:            {sign}{abs(delta):.3f}")
    else:
        lines.append("  delta:            [dim]n/a[/]")
    return "\n".join(lines)


def _read_yaml_preview(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = raw.splitlines()
    if len(lines) > _YAML_PREVIEW_LINES:
        lines = lines[:_YAML_PREVIEW_LINES] + [f"... (+{len(lines) - _YAML_PREVIEW_LINES} more lines)"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Value extraction — defensive against missing/legacy fields.
# ---------------------------------------------------------------------------


def _extract_config_path(view: AttemptLineageView, key: str) -> str | None:
    """Look up a config path from the view.

    ``AttemptLineageView`` does not expose ``baseline_config_path`` /
    ``candidate_config_path`` as first-class attributes today — they arrive
    via ``**extra`` kwargs on :meth:`ImprovementLineageStore.record_attempt`
    and land in the event payload. Use :func:`getattr` first so this code
    stays forward-compatible if the attributes are promoted later, and fall
    back to scanning the underlying event stream.
    """
    attr = getattr(view, key, None)
    if isinstance(attr, str) and attr:
        return attr
    # Scan events (most recent wins) for the payload key.
    for event in reversed(view.events):
        if event.event_type != EVENT_ATTEMPT:
            continue
        payload: dict[str, Any] = event.payload or {}
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _coalesce_score_before(view: AttemptLineageView) -> float | None:
    for attr in ("verification_score_before", "score_before"):
        val = getattr(view, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _coalesce_score_after(view: AttemptLineageView) -> float | None:
    for attr in ("verification_score_after", "score_after"):
        val = getattr(view, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _coalesce_delta(
    view: AttemptLineageView, before: float | None, after: float | None
) -> float | None:
    for attr in ("verification_composite_delta", "composite_delta"):
        val = getattr(view, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
    if before is not None and after is not None:
        return after - before
    return None


# ---------------------------------------------------------------------------
# Context plumbing.
# ---------------------------------------------------------------------------


def _resolve_store(ctx: SlashContext) -> ImprovementLineageStore | None:
    cached = ctx.meta.get("lineage_store")
    if isinstance(cached, ImprovementLineageStore):
        return cached
    db_path = ctx.meta.get("lineage_db_path")
    if isinstance(db_path, (str, Path)):
        store = ImprovementLineageStore(db_path=str(db_path))
        ctx.meta["lineage_store"] = store
        return store
    return None


def _first_token(args: tuple[str, ...]) -> str:
    for arg in args:
        token = arg.strip()
        if token:
            return token
    return ""


__all__ = [
    "build_attempt_diff_command",
]
