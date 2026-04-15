"""Plan-mode workflow.

Elevates the existing ``plan`` permission flag into a discrete workflow with
four states:

* ``idle``      — no plan active; tools obey the workspace permission mode.
* ``drafting``  — a plan document is being written; only read-only /
                  inspection tools are allowed regardless of mode.
* ``approved``  — user accepted the plan; full permission mode restored
                  while the plan stays on disk for reference.
* ``archived``  — plan concluded or discarded; retained on disk for
                  session history but the workflow is back to ``idle``.

The workflow lives alongside :class:`PermissionManager` (``cli/permissions.py``)
so the permission layer can ask ``plan_workflow.active_restriction()`` for a
tool whitelist when drafting is active. This keeps the two layers composable:
a user in ``acceptEdits`` mode who enters ``/plan`` still has edits blocked
until the plan is approved.

Plans persist to ``.agentlab/plans/<plan-id>.md`` so ``/plan`` survives a
workbench restart — mirroring Claude Code's ``.claude/plan.md`` behaviour
but with an id so multiple plans can coexist across sessions.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable


PLAN_DIRNAME = ".agentlab/plans"
INDEX_FILENAME = "_index.json"


DRAFTING_ALLOWED_TOOLS = frozenset(
    {
        "FileRead",
        "Glob",
        "Grep",
        "ConfigRead",
        # ExitPlanMode is how the model tells the user the draft is
        # ready. Denying it would trap the model inside the restricted
        # surface with no legal way to transition out.
        "ExitPlanMode",
    }
)
"""Tools that may run while a plan is being drafted.

These mirror Claude Code's plan-mode allow-list: the model can read the
workspace freely but must not mutate anything until the user approves. Any
tool outside this set is denied by :func:`PlanWorkflow.decision_for_tool`.
"""


class PlanState(str, Enum):
    """Discrete plan-mode state."""

    IDLE = "idle"
    DRAFTING = "drafting"
    APPROVED = "approved"
    ARCHIVED = "archived"


@dataclass
class Plan:
    """Serialisable plan record.

    Lives on disk at ``.agentlab/plans/<id>.md`` with a small JSON index so
    ``PlanStore.list()`` can show the most recent plans without parsing
    every markdown body.
    """

    id: str
    title: str
    state: PlanState
    body: str
    created_at: str
    updated_at: str
    session_id: str | None = None

    def to_markdown(self) -> str:
        """Serialise to markdown with a YAML-style front matter block so a
        human opening the file sees the metadata alongside the body."""
        lines = [
            "---",
            f"id: {self.id}",
            f"title: {self.title}",
            f"state: {self.state.value}",
            f"created_at: {self.created_at}",
            f"updated_at: {self.updated_at}",
        ]
        if self.session_id:
            lines.append(f"session_id: {self.session_id}")
        lines.append("---")
        lines.append("")
        lines.append(self.body)
        return "\n".join(lines) + ("" if self.body.endswith("\n") else "\n")

    @classmethod
    def from_markdown(cls, text: str) -> "Plan":
        """Parse markdown produced by :meth:`to_markdown`.

        Raises :class:`ValueError` when the front matter is missing — the
        plan store is the sole writer, so malformed files indicate a bug or
        external corruption rather than a supported input format."""
        if not text.startswith("---\n"):
            raise ValueError("Plan markdown missing front matter.")
        _, rest = text.split("---\n", 1)
        if "---\n" not in rest:
            raise ValueError("Plan markdown missing closing front matter delimiter.")
        header_block, body = rest.split("---\n", 1)
        headers: dict[str, str] = {}
        for line in header_block.splitlines():
            if not line.strip():
                continue
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()

        required = {"id", "title", "state", "created_at", "updated_at"}
        missing = required - headers.keys()
        if missing:
            raise ValueError(f"Plan markdown missing keys: {sorted(missing)}")

        return cls(
            id=headers["id"],
            title=headers["title"],
            state=PlanState(headers["state"]),
            body=body.lstrip("\n"),
            created_at=headers["created_at"],
            updated_at=headers["updated_at"],
            session_id=headers.get("session_id") or None,
        )


@dataclass
class PlanStore:
    """Persistence layer for plans under ``.agentlab/plans/``.

    Uses a tiny JSON index file so ``list()`` is O(index-size) rather than
    scanning every markdown body — plans accumulate over a long-running
    workspace and we want ``/sessions`` / status queries to stay fast.
    """

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    @property
    def plan_dir(self) -> Path:
        return self.root / PLAN_DIRNAME

    @property
    def index_path(self) -> Path:
        return self.plan_dir / INDEX_FILENAME

    def _plan_path(self, plan_id: str) -> Path:
        return self.plan_dir / f"{plan_id}.md"

    def save(self, plan: Plan) -> Path:
        """Write ``plan`` to disk and refresh the index.

        The index is rewritten in full every save because plans are small
        and the alternative (incremental patches) would add a partial-write
        failure mode for marginal gain."""
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        path = self._plan_path(plan.id)
        path.write_text(plan.to_markdown(), encoding="utf-8")
        self._write_index(self._refresh_index(plan))
        return path

    def load(self, plan_id: str) -> Plan:
        path = self._plan_path(plan_id)
        if not path.exists():
            raise FileNotFoundError(f"Plan not found: {plan_id}")
        return Plan.from_markdown(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        """Return index entries sorted by ``updated_at`` (newest first)."""
        if not self.index_path.exists():
            return []
        try:
            entries = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(entries, list):
            return []
        entries.sort(key=lambda entry: entry.get("updated_at", ""), reverse=True)
        return entries

    def latest_drafting(self) -> Plan | None:
        """Return the most recent plan still in ``drafting`` or ``approved``
        state so workbench restart can resume a workflow."""
        for entry in self.list():
            if entry.get("state") in {PlanState.DRAFTING.value, PlanState.APPROVED.value}:
                try:
                    return self.load(entry["id"])
                except (FileNotFoundError, ValueError):
                    continue
        return None

    def _refresh_index(self, plan: Plan) -> list[dict]:
        entries = [entry for entry in self.list() if entry.get("id") != plan.id]
        entries.append(
            {
                "id": plan.id,
                "title": plan.title,
                "state": plan.state.value,
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
            }
        )
        return entries

    def _write_index(self, entries: Iterable[dict]) -> None:
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(list(entries), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@dataclass
class PlanWorkflow:
    """State machine driving plan-mode transitions.

    The workflow is the single source of truth for "am I planning right now?"
    — :class:`PermissionManager` queries it before consulting mode rules so a
    drafting plan always restricts the tool surface, regardless of what the
    user's saved mode says.

    Transitions are intentionally narrow: the only legal moves are
    ``idle → drafting`` (:meth:`begin`), ``drafting → approved`` (:meth:`approve`),
    ``drafting → archived`` (:meth:`discard`), and ``approved → archived``
    (:meth:`complete`). Any other transition raises :class:`PlanStateError`
    so the REPL can surface a clear "can't do that now" message.
    """

    store: PlanStore
    session_id: str | None = None
    current: Plan | None = field(default=None)

    def __post_init__(self) -> None:
        # Restore an in-flight plan from disk so a workbench restart picks
        # up where the user left off — same approach Claude Code takes with
        # ``.claude/plan.md`` but we use the explicit index to find it.
        if self.current is None:
            self.current = self.store.latest_drafting()

    # ---------------------------------------------------------------- state

    @property
    def state(self) -> PlanState:
        return self.current.state if self.current else PlanState.IDLE

    @property
    def active(self) -> bool:
        """``True`` when a plan is drafting or approved — i.e. the user is
        inside the plan-mode flow."""
        return self.state in {PlanState.DRAFTING, PlanState.APPROVED}

    def active_restriction(self) -> frozenset[str] | None:
        """Return the tool whitelist that applies *right now*, or ``None``.

        Only ``drafting`` restricts tool choice; ``approved`` means the user
        signed off on the plan and the normal permission mode is back in
        charge."""
        if self.state is PlanState.DRAFTING:
            return DRAFTING_ALLOWED_TOOLS
        return None

    # ---------------------------------------------------------------- transitions

    def begin(self, title: str, body: str = "") -> Plan:
        """Start a new plan in ``drafting``.

        Raises :class:`PlanStateError` when a plan is already in flight so
        the caller surfaces "discard or approve the current plan first"
        rather than silently replacing it."""
        if self.current and self.current.state in {PlanState.DRAFTING, PlanState.APPROVED}:
            raise PlanStateError(
                f"Plan '{self.current.title}' is already {self.current.state.value}. "
                "Use /plan-discard or /plan-done before starting a new one."
            )
        now = _utc_now()
        plan = Plan(
            id=_new_plan_id(title),
            title=title.strip() or "Untitled plan",
            state=PlanState.DRAFTING,
            body=body,
            created_at=now,
            updated_at=now,
            session_id=self.session_id,
        )
        self.store.save(plan)
        self.current = plan
        return plan

    def update_body(self, body: str) -> Plan:
        """Replace the plan body (used when the model writes the plan)."""
        plan = self._require_current(PlanState.DRAFTING)
        plan.body = body
        plan.updated_at = _utc_now()
        self.store.save(plan)
        return plan

    def approve(self) -> Plan:
        """Transition ``drafting → approved``.

        Approval is the gate that unlocks the full permission mode again —
        the user has read the plan and consented to it running."""
        plan = self._require_current(PlanState.DRAFTING)
        plan.state = PlanState.APPROVED
        plan.updated_at = _utc_now()
        self.store.save(plan)
        return plan

    def discard(self) -> Plan | None:
        """Archive the current plan from ``drafting`` or ``approved``.

        Returns the archived plan (may be ``None`` when no plan was active,
        because ``/plan-discard`` is idempotent from the user's perspective)."""
        if not self.current or self.current.state in {PlanState.ARCHIVED, PlanState.IDLE}:
            return None
        self.current.state = PlanState.ARCHIVED
        self.current.updated_at = _utc_now()
        self.store.save(self.current)
        archived = self.current
        self.current = None
        return archived

    def complete(self) -> Plan | None:
        """Mark an ``approved`` plan as finished (``archived``)."""
        if not self.current or self.current.state is not PlanState.APPROVED:
            return None
        self.current.state = PlanState.ARCHIVED
        self.current.updated_at = _utc_now()
        self.store.save(self.current)
        completed = self.current
        self.current = None
        return completed

    # ---------------------------------------------------------------- helpers

    def _require_current(self, expected: PlanState) -> Plan:
        if not self.current:
            raise PlanStateError("No plan is active. Use /plan <goal> to start one.")
        if self.current.state is not expected:
            raise PlanStateError(
                f"Plan is {self.current.state.value}; expected {expected.value}."
            )
        return self.current


class PlanStateError(RuntimeError):
    """Raised for illegal transitions — carries a user-facing message."""


# ---------------------------------------------------------------------------
# Permission integration
# ---------------------------------------------------------------------------


def decision_for_tool_with_workflow(
    tool_name: str,
    read_only: bool,
    workflow: PlanWorkflow | None,
    fallback_decision: str,
) -> str:
    """Compose plan-mode restrictions with the permission-manager decision.

    ``fallback_decision`` is what :meth:`PermissionManager.decision_for_tool`
    would have returned; this function only overrides it when a plan is
    drafting and the tool isn't on the whitelist.
    """
    if workflow is None:
        return fallback_decision
    restriction = workflow.active_restriction()
    if restriction is None:
        return fallback_decision
    if tool_name in restriction or read_only:
        return fallback_decision
    return "deny"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _new_plan_id(title: str) -> str:
    """Return a filesystem-safe id: ``<YYYYMMDD-HHMMSS>-<short-slug>``.

    Including the timestamp prefix gives plans a natural chronological sort
    in directory listings (a human opening ``.agentlab/plans/`` can tell
    what's new at a glance)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")[:40] or "plan"
    suffix = uuid.uuid4().hex[:6]
    return f"{stamp}-{slug}-{suffix}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
