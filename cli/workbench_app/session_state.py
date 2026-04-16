"""Workbench session state — the single shared record of REPL progress.

A :class:`WorkbenchSession` captures the minimal cross-turn state the
Workbench needs: which agent config is active, the last eval run, the
last attempt, and a running cost ticker. It is intentionally a single
flat dataclass (no nested state machines) guarded by one
:class:`threading.Lock` so background panels, slash commands, and the
render loop can all read/write it without stepping on each other.

When given a ``_path``, every mutation atomically flushes to
``.agentlab/workbench_session.json`` (``os.replace`` on a temp sibling)
so a crashed REPL never leaves a half-written file on disk. Load is
forgiving: missing files and corrupt JSON both return a fresh default
instance rather than raising — the Workbench should start cleanly even
if the operator hand-edited the file into garbage.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


_SERIALIZED_FIELDS = (
    "current_config_path",
    "last_eval_run_id",
    "last_attempt_id",
    "cost_ticker_usd",
)


@dataclass
class WorkbenchSession:
    """Mutable snapshot of Workbench cross-turn state."""

    current_config_path: str | None = None
    last_eval_run_id: str | None = None
    last_attempt_id: str | None = None
    cost_ticker_usd: float = 0.0

    # Internals: excluded from equality, repr, and on-disk serialization.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )
    _path: Path | None = field(default=None, repr=False, compare=False)

    def update(self, **changes: Any) -> None:
        """Atomically mutate one or more public fields and flush to disk.

        Raises :class:`ValueError` if any key starts with ``_`` — internal
        attributes are not caller-controlled.
        """
        for key in changes:
            if key.startswith("_"):
                raise ValueError(f"Cannot update private field: {key}")
        public_names = {f.name for f in fields(self) if not f.name.startswith("_")}
        for key in changes:
            if key not in public_names:
                raise ValueError(f"Unknown session field: {key}")

        with self._lock:
            for key, value in changes.items():
                setattr(self, key, value)
            self._flush_locked()

    def increment_cost(self, delta_usd: float) -> None:
        """Atomically bump ``cost_ticker_usd`` and flush."""
        with self._lock:
            self.cost_ticker_usd += delta_usd
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Serialize to ``self._path`` atomically. Caller must hold the lock."""
        if self._path is None:
            return
        payload: dict[str, Any] = {"version": 1}
        for name in _SERIALIZED_FIELDS:
            payload[name] = getattr(self, name)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(str(tmp), str(self._path))

    @classmethod
    def load(cls, path: Path) -> WorkbenchSession:
        """Read a session from disk, tolerating missing and corrupt files."""
        if not path.exists():
            return cls(_path=path)
        try:
            raw = path.read_text()
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            logger.warning("workbench session at %s is unreadable: %s", path, exc)
            return cls(_path=path)
        if not isinstance(data, dict):
            logger.warning("workbench session at %s is not a JSON object", path)
            return cls(_path=path)

        kwargs: dict[str, Any] = {}
        for name in _SERIALIZED_FIELDS:
            if name in data:
                kwargs[name] = data[name]
        # Unknown top-level keys (including "version") are silently ignored
        # so forward-compat fields don't break older readers.
        return cls(_path=path, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return the serialized public state (for debugging / tests)."""
        full = asdict(self)
        return {k: full[k] for k in _SERIALIZED_FIELDS}


def load_workbench_session(workspace_root: Path | None) -> WorkbenchSession:
    """Load (or create) the session rooted at ``workspace_root``.

    ``workspace_root=None`` yields an in-memory session (no ``_path``);
    otherwise the ``.agentlab/`` directory is created if needed and the
    session is loaded from ``workbench_session.json`` within it.
    """
    if workspace_root is None:
        return WorkbenchSession()
    agentlab_dir = workspace_root / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    return WorkbenchSession.load(agentlab_dir / "workbench_session.json")


__all__ = [
    "WorkbenchSession",
    "load_workbench_session",
]
