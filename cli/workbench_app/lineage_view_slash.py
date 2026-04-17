"""`/lineage <id>` — ancestry visualizer for R2 improvement lineage (R4.11).

Accepts any node id (eval_run, attempt, deployment, measurement,
verification) and renders the full chain as an indented tree:

    eval_run ev_abc [score: 0.82] (2026-04-17T12:00:00)
    └── attempt att_123 [candidate] (2026-04-17T12:05:00)
        ├── deployment dep_456 [staging] (2026-04-17T12:10:00)
        └── measurement meas_789 [score_after: 0.89, delta: +0.07] (…)

The node that matched the user's ``<id>`` is wrapped in ``[bold yellow]…[/]``;
others render as ``[dim]…[/]``. Unknown ids surface a red error line instead
of raising.

Slash context ``meta`` keys honoured:

- ``lineage_store`` — caller-supplied :class:`ImprovementLineageStore`.
- ``lineage_db_path`` — fallback sqlite path if no store is cached.
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    EVENT_DEPLOYMENT,
    EVENT_EVAL_RUN,
    EVENT_MEASUREMENT,
    EVENT_REJECTION,
    EVENT_VERIFICATION,
    AttemptLineageView,
    ImprovementLineageStore,
)


def build_lineage_view_command() -> LocalCommand:
    """Build the ``/lineage`` slash command."""
    return LocalCommand(
        name="lineage",
        description="Show the ancestry chain for any lineage node id",
        handler=_handle_lineage_view,
        source="builtin",
        argument_hint="<id>",
        when_to_use=(
            "Use to trace a node (eval run, attempt, deployment, or "
            "measurement id) back through the R2 improvement lineage."
        ),
        sensitive=False,
    )


# ---------------------------------------------------------------------------
# Handler.
# ---------------------------------------------------------------------------


@dataclass
class _Resolved:
    """A resolved node: the attempt_id that anchors the chain + which node
    type/id the user referenced."""

    attempt_id: str
    matched_kind: str  # "eval_run" | "attempt" | "deployment" | "measurement" | "verification"
    matched_id: str


def _handle_lineage_view(ctx: SlashContext, *args: str) -> OnDoneResult:
    node_id = _first_token(args)
    if not node_id:
        return on_done("  Usage: /lineage <id>", display="system")

    store = _resolve_store(ctx)
    if store is None:
        return on_done(
            "  No lineage store available. Pass `lineage_store` via slash context.",
            display="system",
        )

    resolved = _resolve_node(store, node_id)
    if resolved is None:
        return on_done(f"[red]Unknown lineage id: {node_id}[/]", display="system")

    view = store.view_attempt(resolved.attempt_id)
    if not view.events:
        return on_done(f"[red]Unknown lineage id: {node_id}[/]", display="system")

    tree = _render_tree(view, resolved)
    return on_done(tree, display="user")


# ---------------------------------------------------------------------------
# Resolution.
# ---------------------------------------------------------------------------


def _resolve_node(
    store: ImprovementLineageStore, node_id: str
) -> _Resolved | None:
    """Resolve *node_id* to an anchor attempt_id and a node kind.

    Strategy:
      1. Try ``view_attempt(node_id)`` — non-empty if it's an attempt_id.
      2. Otherwise scan raw sqlite payloads for a matching
         eval_run_id / deployment_id / measurement_id / verification_id.
      3. Fall back to scanning for an ``event_id`` match.
    """
    # (1) Direct attempt id hit.
    view = store.view_attempt(node_id)
    if view.events:
        return _Resolved(
            attempt_id=node_id,
            matched_kind="attempt",
            matched_id=node_id,
        )

    # (2) Payload-scoped id lookup via direct sqlite SELECT.
    # We intentionally read the internal sqlite file here (see C5 task
    # invariants) rather than adding a public method to the store.
    payload_keys_by_kind: dict[str, str] = {
        "eval_run": "eval_run_id",
        "deployment": "deployment_id",
        "measurement": "measurement_id",
        "verification": "verification_id",
    }
    event_type_for_kind: dict[str, str] = {
        "eval_run": EVENT_EVAL_RUN,
        "deployment": EVENT_DEPLOYMENT,
        "measurement": EVENT_MEASUREMENT,
        "verification": EVENT_VERIFICATION,
    }

    try:
        with sqlite3.connect(store.db_path) as conn:
            rows = conn.execute(
                "SELECT event_id, attempt_id, event_type, payload "
                "FROM lineage_events"
            ).fetchall()
    except sqlite3.Error:
        return None

    for event_id, attempt_id, event_type, payload_json in rows:
        # (3) event_id match — rare, but the task permits it.
        if event_id == node_id and attempt_id:
            kind = _kind_from_event_type(event_type)
            if kind:
                return _Resolved(
                    attempt_id=attempt_id,
                    matched_kind=kind,
                    matched_id=node_id,
                )
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        for kind, key in payload_keys_by_kind.items():
            expected_type = event_type_for_kind[kind]
            # Payload keys can appear on multiple event types (e.g.
            # `eval_run_id` shows up on attempt events too). Match only
            # when the event type lines up with the kind we're reporting.
            if event_type != expected_type:
                continue
            if payload.get(key) == node_id and attempt_id:
                return _Resolved(
                    attempt_id=attempt_id,
                    matched_kind=kind,
                    matched_id=node_id,
                )

    return None


def _kind_from_event_type(event_type: str) -> str | None:
    mapping = {
        EVENT_EVAL_RUN: "eval_run",
        EVENT_ATTEMPT: "attempt",
        EVENT_DEPLOYMENT: "deployment",
        EVENT_MEASUREMENT: "measurement",
        EVENT_VERIFICATION: "verification",
        EVENT_REJECTION: "rejection",
    }
    return mapping.get(event_type)


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------


def _render_tree(view: AttemptLineageView, resolved: _Resolved) -> str:
    """Render the ancestry chain as an indented tree.

    Layout:
        eval_run <id> [score: x.xx] (ts)
        └── attempt <id> [status] (ts)
            ├── deployment <id> [env] (ts)
            └── measurement <id> [score_after: x.xx, delta: +x.xx] (ts)
    """
    # Extract timestamps + payloads per event type (latest event of each
    # kind wins — consistent with view_attempt's flattening rule).
    eval_run_ev = _latest_event(view, EVENT_EVAL_RUN)
    attempt_ev = _latest_event(view, EVENT_ATTEMPT)
    deployment_ev = _latest_event(view, EVENT_DEPLOYMENT)
    measurement_ev = _latest_event(view, EVENT_MEASUREMENT)

    lines: list[str] = []

    # eval_run line (top of chain).
    if view.eval_run_id:
        payload = eval_run_ev.payload if eval_run_ev else {}
        score = payload.get("composite_score")
        bits: list[str] = []
        if score is not None:
            try:
                bits.append(f"score: {float(score):.2f}")
            except (TypeError, ValueError):
                pass
        ts = _fmt_ts(eval_run_ev.timestamp if eval_run_ev else None)
        label = _compose_label(
            f"eval_run {view.eval_run_id}", bits, ts
        )
        lines.append(_style(label, highlight=(resolved.matched_kind == "eval_run")))

    # attempt line.
    attempt_payload = attempt_ev.payload if attempt_ev else {}
    status = attempt_payload.get("status") or view.status
    bits = []
    if status:
        bits.append(str(status))
    ts = _fmt_ts(attempt_ev.timestamp if attempt_ev else None)
    attempt_label = _compose_label(
        f"attempt {view.attempt_id}", bits, ts
    )
    # Indent attempt under eval_run if one exists.
    prefix = "└── " if view.eval_run_id else ""
    lines.append(
        _style(prefix + attempt_label, highlight=(resolved.matched_kind == "attempt"))
    )

    # Children of attempt (deployment + measurement). Use ├── for all but
    # the last to keep the tree visually correct.
    child_indent = "    " if view.eval_run_id else ""
    children: list[tuple[str, bool]] = []  # (line_body, highlight)

    if view.deployment_id:
        payload = deployment_ev.payload if deployment_ev else {}
        dep_bits: list[str] = []
        env = payload.get("env") or payload.get("environment")
        if env:
            dep_bits.append(str(env))
        if view.deployed_version is not None:
            dep_bits.append(f"v{view.deployed_version}")
        ts = _fmt_ts(deployment_ev.timestamp if deployment_ev else None)
        label = _compose_label(
            f"deployment {view.deployment_id}", dep_bits, ts
        )
        children.append((label, resolved.matched_kind == "deployment"))

    if view.measurement_id:
        payload = measurement_ev.payload if measurement_ev else {}
        m_bits: list[str] = []
        # Prefer the view's score_after / composite_delta (already
        # flattened); fall back to payload values.
        score_after = view.score_after
        if score_after is None:
            score_after = payload.get("score_after")
        delta = view.composite_delta
        if delta is None:
            delta = payload.get("composite_delta")
        if score_after is not None:
            try:
                m_bits.append(f"score_after: {float(score_after):.2f}")
            except (TypeError, ValueError):
                pass
        if delta is not None:
            try:
                d = float(delta)
                sign = "+" if d >= 0 else "-"
                m_bits.append(f"delta: {sign}{abs(d):.2f}")
            except (TypeError, ValueError):
                pass
        ts = _fmt_ts(measurement_ev.timestamp if measurement_ev else None)
        label = _compose_label(
            f"measurement {view.measurement_id}", m_bits, ts
        )
        children.append((label, resolved.matched_kind == "measurement"))

    for i, (body, is_highlight) in enumerate(children):
        connector = "└── " if i == len(children) - 1 else "├── "
        lines.append(
            _style(child_indent + connector + body, highlight=is_highlight)
        )

    return "\n".join(lines)


def _compose_label(head: str, bits: list[str], ts: str | None) -> str:
    segments = [head]
    if bits:
        segments.append(f"[{', '.join(bits)}]")
    if ts:
        segments.append(f"({ts})")
    return " ".join(segments)


def _style(text: str, *, highlight: bool) -> str:
    if highlight:
        return f"[bold yellow]{text}[/]"
    return f"[dim]{text}[/]"


def _latest_event(view: AttemptLineageView, event_type: str):
    """Return the most recent event of *event_type* in *view*, or None."""
    for ev in reversed(view.events):
        if ev.event_type == event_type:
            return ev
    return None


def _fmt_ts(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    try:
        dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    # Strip microseconds + tz suffix for a compact render.
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "")


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
    "build_lineage_view_command",
]
