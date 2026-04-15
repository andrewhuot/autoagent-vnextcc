"""Transcript-level checkpoints for session rewind.

The existing :class:`cli.workbench_app.checkpoint.CheckpointManager` handles
*agent-config* rollbacks — it restores ``configs/v{NNN}.yaml`` files. This
module complements it with *conversation-level* rollbacks: the user has
been typing for ten turns, wants to undo the last three, and keep the
rest.

Data model:

* One :class:`TranscriptCheckpoint` per persisted snapshot.
* Each checkpoint captures the transcript-length marker, a label, an
  optional note, and the timestamp. The actual transcript lives on the
  :class:`cli.sessions.Session` — rewind simply trims the transcript list
  back to the checkpoint's message index, which is cheap and reversible
  before the session is saved.
* Checkpoints persist alongside the session under
  ``.agentlab/sessions/<session-id>.checkpoints.json`` so the user can
  rewind across workbench restarts.

Why not re-use the config checkpoint manager: agent-config rollbacks and
transcript rewinds have opposite failure modes (configs are expected to
be atomic, transcripts are expected to be incremental) and different
identity schemes (integer versions vs message-index markers). Merging
them would force one concept to carry the other's semantics.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from cli.sessions import Session, SessionStore


CHECKPOINT_SUFFIX = ".checkpoints.json"


@dataclass
class TranscriptCheckpoint:
    """One rewindable transcript-length marker."""

    checkpoint_id: str
    session_id: str
    message_index: int
    """Number of transcript entries *kept* on rewind — i.e. the length the
    transcript will shrink to."""

    label: str = ""
    note: str = ""
    created_at: float = 0.0
    auto: bool = False
    """Distinguishes user-initiated snapshots (``False``) from automatic
    per-turn snapshots (``True``) so ``/transcript-rewind`` can filter the
    noisier auto entries by default."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptCheckpoint":
        return cls(
            checkpoint_id=str(data.get("checkpoint_id", "")),
            session_id=str(data.get("session_id", "")),
            message_index=int(data.get("message_index", 0)),
            label=str(data.get("label", "")),
            note=str(data.get("note", "")),
            created_at=float(data.get("created_at", 0.0)),
            auto=bool(data.get("auto", False)),
        )


@dataclass
class TranscriptCheckpointStore:
    """Persistence for :class:`TranscriptCheckpoint` per session.

    One JSON file per session keeps list rewrites cheap (checkpoints are
    small), mirrors the existing :class:`SessionStore` file-per-session
    layout, and sidesteps a shared lock-file design."""

    workspace_dir: Path
    subdir: str = "sessions"

    def __post_init__(self) -> None:
        self._dir = Path(self.workspace_dir) / ".agentlab" / self.subdir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        return self._dir / f"{session_id}{CHECKPOINT_SUFFIX}"

    def save_all(self, session_id: str, checkpoints: Iterable[TranscriptCheckpoint]) -> Path:
        """Rewrite the checkpoint list in full — list is small; atomic semantics
        are not worth the extra complexity of patching individual entries."""
        path = self._path_for(session_id)
        payload = [cp.to_dict() for cp in checkpoints]
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, session_id: str) -> list[TranscriptCheckpoint]:
        path = self._path_for(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [TranscriptCheckpoint.from_dict(entry) for entry in data]


@dataclass
class TranscriptRewindManager:
    """High-level API the REPL / slash handlers consume.

    The manager orchestrates three responsibilities that were tempting to
    spread across the callers:

    1. Decide when a checkpoint should auto-snapshot (after assistant turns).
    2. Persist checkpoints via :class:`TranscriptCheckpointStore`.
    3. Rewind the active :class:`Session.transcript` to a checkpoint and
       hand the updated session back to :class:`SessionStore` for save.

    Keeping that logic here means the slash handler is ~five lines of
    dispatch and tests can exercise the manager directly without a REPL.
    """

    store: TranscriptCheckpointStore
    session_store: SessionStore
    auto_threshold: int = 1
    """Minimum transcript delta (messages) between auto-checkpoints. ``1``
    matches Claude Code's per-turn cadence; raise this for large sessions
    where the auto list starts to dominate."""

    def snapshot(
        self,
        session: Session,
        *,
        label: str = "",
        note: str = "",
        auto: bool = False,
    ) -> TranscriptCheckpoint:
        """Persist a checkpoint at the current transcript length."""
        checkpoint = TranscriptCheckpoint(
            checkpoint_id=uuid.uuid4().hex[:10],
            session_id=session.session_id,
            message_index=len(session.transcript),
            label=label or self._default_label(session, auto),
            note=note,
            created_at=time.time(),
            auto=auto,
        )
        checkpoints = self.store.load(session.session_id) + [checkpoint]
        self.store.save_all(session.session_id, checkpoints)
        return checkpoint

    def maybe_snapshot_after_assistant_turn(
        self, session: Session
    ) -> TranscriptCheckpoint | None:
        """Auto-snapshot if the transcript has grown past ``auto_threshold``.

        Returns the new checkpoint or ``None`` when an auto-checkpoint
        already exists at this message index (avoids stacking duplicates
        when the REPL calls this helper defensively)."""
        transcript_len = len(session.transcript)
        if transcript_len == 0:
            return None
        existing = self.store.load(session.session_id)
        most_recent_auto_index = max(
            (cp.message_index for cp in existing if cp.auto),
            default=-1,
        )
        if transcript_len - most_recent_auto_index < self.auto_threshold:
            return None
        return self.snapshot(session, auto=True)

    def list(self, session_id: str, *, include_auto: bool = True) -> list[TranscriptCheckpoint]:
        """Return checkpoints newest-first."""
        checkpoints = self.store.load(session_id)
        if not include_auto:
            checkpoints = [cp for cp in checkpoints if not cp.auto]
        checkpoints.sort(key=lambda cp: cp.created_at, reverse=True)
        return checkpoints

    def rewind(
        self, session: Session, checkpoint_id: str
    ) -> tuple[TranscriptCheckpoint, int]:
        """Trim ``session.transcript`` back to ``checkpoint.message_index``.

        Returns the chosen checkpoint plus the number of messages dropped
        so the caller can surface "rewound past N messages" in the UI.
        Raises :class:`ValueError` when the checkpoint is unknown so the
        REPL can surface a specific error."""
        target = self._find(session.session_id, checkpoint_id)
        if target is None:
            raise ValueError(f"Unknown transcript checkpoint: {checkpoint_id}")

        removed = max(0, len(session.transcript) - target.message_index)
        session.transcript = session.transcript[: target.message_index]
        session.updated_at = time.time()
        self.session_store.save(session)
        return target, removed

    # ------------------------------------------------------------------ helpers

    def _find(self, session_id: str, checkpoint_id: str) -> TranscriptCheckpoint | None:
        for cp in self.store.load(session_id):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    @staticmethod
    def _default_label(session: Session, auto: bool) -> str:
        """Sensible default label when the caller didn't pass one.

        Auto-checkpoints get a role-suffixed label pointing to the message
        that triggered them; manual checkpoints fall back to a short
        session-local index for readability."""
        if auto and session.transcript:
            last = session.transcript[-1]
            role = (last.role or "turn").replace("_", " ")
            return f"after {role} turn"
        return f"manual #{len(session.transcript)}"


__all__ = [
    "CHECKPOINT_SUFFIX",
    "TranscriptCheckpoint",
    "TranscriptCheckpointStore",
    "TranscriptRewindManager",
]
