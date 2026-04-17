"""Workspace-persisted allowlist for the transcript classifier.

The permission dialog's "save as rule" option writes into two places:

* :meth:`PermissionManager.persist_allow_rule` — appends to
  ``settings.json::permissions.rules.allow``. This is the legacy
  allow-rule path consumed by :meth:`PermissionManager.decision_for`.
* :func:`append_persisted_allow` (this module) — appends to
  ``<root>/.agentlab/classifier_allowlist.json``. The next session's
  :class:`~cli.permissions.classifier.ClassifierContext` factory reads
  this file into ``persisted_allow_patterns`` so the classifier can
  short-circuit (AUTO_APPROVE) without re-prompting.

The two stores are kept separate so a narrowly-scoped classifier rule
can be added without widening the permission manager's explicit
allowlist (which also affects non-classifier call paths).

Failure modes:

* Missing file → empty set.
* Unreadable / malformed JSON → empty set, logged at DEBUG. A fresh
  append writes a clean file on top of it.
* Write failures are swallowed and logged at DEBUG — the caller should
  never crash because of a best-effort persistence step.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

CLASSIFIER_ALLOWLIST_FILENAME = "classifier_allowlist.json"


def _allowlist_path(root: str | Path) -> Path:
    return Path(root) / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME


def load_persisted_patterns(root: str | Path) -> frozenset[str]:
    """Return the persisted classifier allow-patterns for ``root``.

    Empty frozenset when the file is missing, unreadable, or malformed.
    Only string entries under the ``allow`` key are returned — any other
    shape is ignored defensively so a hand-edited file can't crash the
    classifier.
    """
    path = _allowlist_path(root)
    if not path.exists():
        return frozenset()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        _LOG.debug("classifier allowlist read failed at %s: %s", path, exc)
        return frozenset()
    if not raw.strip():
        return frozenset()
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        _LOG.debug("classifier allowlist malformed at %s: %s", path, exc)
        return frozenset()
    if not isinstance(data, dict):
        return frozenset()
    entries = data.get("allow")
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(entry for entry in entries if isinstance(entry, str) and entry)


def append_persisted_allow(root: str | Path, pattern: str) -> None:
    """Append ``pattern`` to the classifier allowlist file, deduped.

    Creates the ``.agentlab`` directory + the JSON file when missing.
    I/O failures are swallowed and logged at DEBUG — callers must not
    depend on this writing successfully (the classifier still works
    without the persisted file, just with more prompts).
    """
    if not pattern:
        return
    existing = set(load_persisted_patterns(root))
    existing.add(pattern)
    path = _allowlist_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"allow": sorted(existing)}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        _LOG.debug("classifier allowlist write failed at %s: %s", path, exc)


__all__ = [
    "CLASSIFIER_ALLOWLIST_FILENAME",
    "append_persisted_allow",
    "load_persisted_patterns",
]
