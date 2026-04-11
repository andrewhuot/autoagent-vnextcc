"""Plan-tree and artifact data model for the Workbench builder agent.

WHY: The Workbench UI renders a live, nested task tree (Manus-style) and
emits artifact cards inline with the conversation. This module gives both
the backend agent and the API layer one shared, serializable data model so
streaming events and JSON snapshots stay in lockstep.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Optional

from builder.types import new_id


class PlanTaskStatus(str, Enum):
    """Lifecycle states for a plan task. Stored as strings in JSON."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"
    PAUSED = "paused"


ARTIFACT_CATEGORIES = (
    "agent",
    "tool",
    "callback",
    "guardrail",
    "eval",
    "environment",
    "deployment",
    "api_call",
    "plan",
    "note",
)


@dataclass
class PlanTask:
    """One node in the agent-builder plan tree.

    Children produce artifacts; parents aggregate status. The tree is
    flattened for execution via ``walk_leaves``. Parent status is derived
    from children, never set directly.
    """

    id: str
    title: str
    description: str = ""
    status: str = PlanTaskStatus.PENDING.value
    children: list["PlanTask"] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize this task (and children) for JSON transport."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "children": [child.to_dict() for child in self.children],
            "artifact_ids": list(self.artifact_ids),
            "log": list(self.log),
            "parent_id": self.parent_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanTask":
        """Reconstruct a PlanTask (and children) from a JSON dict."""
        return cls(
            id=str(payload.get("id") or new_id()),
            title=str(payload.get("title") or "Task"),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or PlanTaskStatus.PENDING.value),
            children=[cls.from_dict(child) for child in payload.get("children", [])],
            artifact_ids=list(payload.get("artifact_ids", [])),
            log=list(payload.get("log", [])),
            parent_id=payload.get("parent_id"),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
        )


@dataclass
class WorkbenchArtifact:
    """One generated artifact shown in the right-pane preview / source viewer."""

    id: str
    task_id: str
    category: str
    name: str
    summary: str
    preview: str
    source: str
    language: str
    created_at: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize this artifact for JSON transport."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "category": self.category,
            "name": self.name,
            "summary": self.summary,
            "preview": self.preview,
            "source": self.source,
            "language": self.language,
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkbenchArtifact":
        """Reconstruct an artifact from a JSON dict."""
        return cls(
            id=str(payload.get("id") or new_id()),
            task_id=str(payload.get("task_id") or ""),
            category=str(payload.get("category") or "note"),
            name=str(payload.get("name") or "Artifact"),
            summary=str(payload.get("summary") or ""),
            preview=str(payload.get("preview") or ""),
            source=str(payload.get("source") or ""),
            language=str(payload.get("language") or "text"),
            created_at=str(payload.get("created_at") or ""),
            version=int(payload.get("version") or 1),
        )


def find_task(root: PlanTask, task_id: str) -> Optional[PlanTask]:
    """Depth-first search for a task by ID in a plan tree."""
    if root.id == task_id:
        return root
    for child in root.children:
        found = find_task(child, task_id)
        if found is not None:
            return found
    return None


def walk_leaves(root: PlanTask) -> list[PlanTask]:
    """Return leaf tasks in depth-first order; these are what the executor runs."""
    if not root.children:
        return [root]
    leaves: list[PlanTask] = []
    for child in root.children:
        leaves.extend(walk_leaves(child))
    return leaves


def walk_all(root: PlanTask) -> Iterator[PlanTask]:
    """Iterate every task in the tree (parents and leaves), depth-first."""
    yield root
    for child in root.children:
        yield from walk_all(child)


def set_task_status(root: PlanTask, task_id: str, status: str) -> Optional[PlanTask]:
    """Set a single task's status and return the mutated node, or None if not found."""
    task = find_task(root, task_id)
    if task is None:
        return None
    task.status = status
    return task


def recompute_parent_status(root: PlanTask) -> None:
    """Bubble leaf statuses up to parents so the UI shows accurate group states.

    Rules:
      - all children DONE  -> DONE
      - any child ERROR    -> ERROR
      - any child RUNNING  -> RUNNING
      - all children PAUSED -> PAUSED
      - otherwise leave PENDING
    """
    if not root.children:
        return
    for child in root.children:
        recompute_parent_status(child)
    statuses = {child.status for child in root.children}
    if statuses == {PlanTaskStatus.DONE.value}:
        root.status = PlanTaskStatus.DONE.value
    elif PlanTaskStatus.ERROR.value in statuses:
        root.status = PlanTaskStatus.ERROR.value
    elif PlanTaskStatus.RUNNING.value in statuses:
        root.status = PlanTaskStatus.RUNNING.value
    elif statuses == {PlanTaskStatus.PAUSED.value}:
        root.status = PlanTaskStatus.PAUSED.value
    elif PlanTaskStatus.DONE.value in statuses and PlanTaskStatus.PENDING.value in statuses:
        root.status = PlanTaskStatus.RUNNING.value


def clone_plan(root: PlanTask) -> PlanTask:
    """Deep-clone a plan tree. Used when persisting snapshots per version."""
    return PlanTask.from_dict(copy.deepcopy(root.to_dict()))


__all__ = [
    "ARTIFACT_CATEGORIES",
    "PlanTask",
    "PlanTaskStatus",
    "WorkbenchArtifact",
    "clone_plan",
    "find_task",
    "recompute_parent_status",
    "set_task_status",
    "walk_all",
    "walk_leaves",
]
