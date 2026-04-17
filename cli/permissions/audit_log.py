"""Append-only audit log for classifier decisions.

Every call to :meth:`ClassifierAuditLog.record` writes a single JSON
object as a line to ``<root>/.agentlab/classifier_audit.jsonl``. The
file rotates on size: once a new line would push the file past
``max_bytes``, the current log is renamed to ``<name>.1``, older
rotations shift one slot (``.1 -> .2``, ``.2 -> .3``, ...), and the
oldest beyond ``keep`` is deleted.

Why:

* Claude Code's transcript classifier is silent by design — it short-
  circuits prompts. Operators need a way to audit *what was auto-
  approved / auto-denied* after the fact without re-running the
  session.
* We deliberately DO NOT store raw tool inputs. A ``Bash`` command or
  ``FileRead`` path can easily contain secrets (API keys on the CLI,
  customer data in a file). Instead we store a 16-char SHA-256 digest
  so an operator can correlate entries without us writing the secret
  to disk.

Thread safety: the write + rotate path is guarded by a
:class:`threading.Lock` so MCP transport workers and the main executor
thread can share a single instance. The lock is NOT held during reads
(``iter_recent``) — a torn read gracefully skips the malformed line.

Failure modes:

* I/O errors during write/rotate are swallowed and logged at DEBUG.
  The audit log is best-effort infrastructure; a full disk must not
  crash the executor.
* Malformed lines pre-existing in the file are silently skipped during
  ``iter_recent`` — a hand-edited or half-written file still yields
  whatever parses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cli.permissions.classifier import ClassifierDecision

_LOG = logging.getLogger(__name__)

AUDIT_LOG_FILENAME = "classifier_audit.jsonl"

# 10 MiB default matches the settings.json cascade's rotation heuristic.
# Ten lines/second of decisions is still weeks of runway.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_KEEP = 3


def compute_input_digest(tool_input: Any) -> str:
    """Short SHA-256 digest of ``tool_input``.

    ``json.dumps(..., sort_keys=True)`` means semantically equal inputs
    produce the same digest regardless of key order. We truncate to 16
    hex chars (64 bits of entropy) — plenty for audit correlation, and
    short enough not to balloon the log.

    Non-serialisable objects fall through to ``repr()`` so we never
    crash on an exotic tool_input; the digest is then "best effort but
    still deterministic for repeated calls with the same object".
    """
    try:
        serialised = json.dumps(tool_input, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        serialised = repr(tool_input)
    hex_full = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
    return f"sha256:{hex_full[:16]}"


class ClassifierAuditLog:
    """Thread-safe JSONL sink for classifier decisions with size rotation.

    One instance per process is typical, passed through to
    :func:`cli.tools.executor.execute_tool_call` as the ``audit_log``
    kwarg. Tests can pass a throwaway instance pointed at a tmp_path.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        keep: int = _DEFAULT_KEEP,
    ) -> None:
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        # Clamp defensively: ``keep <= 0`` would mean rotation deletes the
        # data it just renamed, which is never what the caller wants.
        self.keep = max(1, int(keep))
        # Re-entrancy isn't needed — ``record`` never calls itself.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        tool_name: str,
        decision: ClassifierDecision,
        tool_input_digest: str,
        reason: str | None = None,
    ) -> None:
        """Append one decision entry. Rotates first if the new line would
        exceed ``max_bytes``.

        I/O failures are swallowed — the caller must not depend on this
        succeeding, and in particular must not crash the executor because
        of a read-only filesystem or a missing parent directory it cannot
        create.
        """
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "decision": decision.value if isinstance(decision, ClassifierDecision) else str(decision),
            "input_digest": tool_input_digest,
        }
        if reason is not None:
            entry["reason"] = reason
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        encoded = line.encode("utf-8")

        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _LOG.debug("audit log mkdir failed at %s: %s", self.path.parent, exc)
                return

            # Rotate before write so the new line always lands in the
            # fresh, below-max_bytes file.
            try:
                current_size = self.path.stat().st_size if self.path.exists() else 0
            except OSError:
                current_size = 0
            if current_size + len(encoded) > self.max_bytes and current_size > 0:
                self._rotate_locked()

            try:
                with self.path.open("ab") as fh:
                    fh.write(encoded)
            except OSError as exc:
                _LOG.debug("audit log write failed at %s: %s", self.path, exc)

    def rotate_if_needed(self) -> None:
        """Public hook for callers that want to force a rotation check.

        The normal path is the rotation inside :meth:`record`; this is
        exposed mainly for tests and for diagnostic tooling that wants
        to rotate proactively (e.g. a ``/doctor`` action).
        """
        with self._lock:
            try:
                current_size = self.path.stat().st_size if self.path.exists() else 0
            except OSError:
                return
            if current_size >= self.max_bytes:
                self._rotate_locked()

    def _rotate_locked(self) -> None:
        """Shift rotated files and rename the current log to ``.1``.

        Must be called with ``self._lock`` held. ``.keep`` is the highest
        numbered file kept; anything older is unlinked. We shift from
        highest to lowest so no rename ever collides.
        """
        # Rename pattern: path -> path.1 -> path.2 -> ... -> path.keep.
        # Anything at path.{keep+1} or higher was out of retention last
        # rotation; if it still exists (e.g. a previous run had a bigger
        # keep), leave it alone — we only touch slots we own.
        try:
            # Delete the oldest slot if it exists.
            oldest = self._rotated_path(self.keep)
            if oldest.exists():
                try:
                    oldest.unlink()
                except OSError as exc:
                    _LOG.debug("audit log unlink oldest %s failed: %s", oldest, exc)
            # Shift .keep-1 -> .keep, ..., .1 -> .2
            for slot in range(self.keep - 1, 0, -1):
                src = self._rotated_path(slot)
                dst = self._rotated_path(slot + 1)
                if src.exists():
                    try:
                        src.replace(dst)
                    except OSError as exc:
                        _LOG.debug("audit log rotate %s -> %s failed: %s", src, dst, exc)
            # Finally, current log -> .1
            if self.path.exists():
                try:
                    self.path.replace(self._rotated_path(1))
                except OSError as exc:
                    _LOG.debug("audit log rotate primary failed: %s", exc)
        except Exception as exc:  # pragma: no cover - defensive, rotation must not crash
            _LOG.debug("audit log rotate crashed: %s", exc)

    def _rotated_path(self, slot: int) -> Path:
        """Return the path of rotation slot ``slot`` (1-indexed).

        For ``audit.jsonl`` this yields ``audit.jsonl.1``,
        ``audit.jsonl.2``, .... We APPEND the rotation index rather than
        replacing the suffix, matching logrotate convention and keeping
        ``.jsonl`` recognisable to downstream tooling.
        """
        return self.path.with_suffix(self.path.suffix + f".{slot}")

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def iter_recent(self, limit: int = 100) -> Iterator[dict[str, Any]]:
        """Yield up to ``limit`` most recent entries from the current log.

        We intentionally do NOT read rotated slots — ``/doctor`` cares
        about "what happened recently", and a full tail would need a
        streaming reverse-line reader that's not worth the complexity
        here. Operators who want history can read the ``.1``..``.keep``
        files directly.

        Malformed lines are silently skipped so a half-written tail
        (rare — we write with ``ab`` so partial writes are bounded to
        the final line) doesn't poison the whole iteration.
        """
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            _LOG.debug("audit log read failed at %s: %s", self.path, exc)
            return
        lines = raw.splitlines()
        # Most recent last; take the tail and reverse if consumers need
        # newest-first. For now yield in file order (oldest-first, which
        # matches how ``tail -n`` + manual scroll feels in /doctor).
        tail = lines[-limit:] if limit > 0 else lines
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(entry, dict):
                yield entry


def default_audit_log(root: str | Path) -> ClassifierAuditLog:
    """Build a ``ClassifierAuditLog`` at ``<root>/.agentlab/<FILENAME>``.

    The directory is created lazily on the first write — this function
    does not touch the filesystem so test fixtures and ``/doctor`` can
    instantiate it cheaply.
    """
    path = Path(root) / ".agentlab" / AUDIT_LOG_FILENAME
    return ClassifierAuditLog(path)


__all__ = [
    "AUDIT_LOG_FILENAME",
    "ClassifierAuditLog",
    "compute_input_digest",
    "default_audit_log",
]
