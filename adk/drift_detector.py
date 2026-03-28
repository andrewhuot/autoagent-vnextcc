"""Drift detection for round-trip ADK source fidelity.

A "round-trip" is the sequence: parse ADK source → map to AutoAgent config →
map back to ADK source → re-parse.  If the re-parsed config differs from the
original the difference is called "drift".  Drift is expected for fields that
are deliberately not round-tripped (e.g. raw function bodies), but any
unexpected drift indicates a bug in the mapper or exporter.

The ``DriftDetector`` class computes a structural diff between two config
dicts and summarises the result in a ``DriftReport``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DriftReport:
    """Summary of structural differences between two config snapshots.

    Attributes:
        has_drift: ``True`` if any drifted fields were detected.
        drift_fields: Dot-separated paths of fields that differ.
        original_hash: SHA-256 hex digest of the original config.
        roundtrip_hash: SHA-256 hex digest of the round-tripped config.
        details: Mapping from field path → ``{"original": ..., "roundtrip": ...}``.
    """

    has_drift: bool
    drift_fields: list[str]
    original_hash: str
    roundtrip_hash: str
    details: dict = field(default_factory=dict)


class DriftDetector:
    """Detect structural drift between an original and a round-tripped config.

    Example::

        detector = DriftDetector()
        report = detector.detect(original_config, roundtripped_config)
        if report.has_drift:
            print("Drift detected in:", report.drift_fields)
    """

    # Keys that are expected to differ after a round-trip and should not be
    # counted as drift.  Add to this set if your exporter intentionally drops
    # or transforms certain fields.
    IGNORED_KEYS: frozenset[str] = frozenset(
        {
            "_adk_function_body",
            "_adk_metadata",
            "_adk_agent_name",
        }
    )

    def detect(
        self,
        original_config: dict,
        roundtripped_config: dict,
    ) -> DriftReport:
        """Compare *original_config* and *roundtripped_config* for drift.

        Recursively walks both dicts and records any paths where values differ,
        where a key is present in one but not the other, or where the type of a
        value changes.  Keys listed in ``IGNORED_KEYS`` are skipped.

        Args:
            original_config: The config dict produced directly from parsing
                the ADK source.
            roundtripped_config: The config dict produced after a full
                ADK → AutoAgent → ADK round-trip.

        Returns:
            A ``DriftReport`` summarising the comparison.
        """
        original_hash = self._hash_config(original_config)
        roundtrip_hash = self._hash_config(roundtripped_config)

        drift_fields = self._compare_fields(original_config, roundtripped_config)
        details: dict[str, Any] = {}
        for path in drift_fields:
            orig_val = self._get_nested(original_config, path)
            rt_val = self._get_nested(roundtripped_config, path)
            details[path] = {"original": orig_val, "roundtrip": rt_val}

        return DriftReport(
            has_drift=bool(drift_fields),
            drift_fields=drift_fields,
            original_hash=original_hash,
            roundtrip_hash=roundtrip_hash,
            details=details,
        )

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def _hash_config(self, config: dict) -> str:
        """Return a stable SHA-256 hex digest of *config*.

        The config is serialised to JSON with sorted keys so that key
        ordering differences do not affect the hash.

        Args:
            config: The config dict to hash.

        Returns:
            Lowercase hex SHA-256 digest string.
        """
        serialised = json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Field comparison
    # ------------------------------------------------------------------

    def _compare_fields(
        self,
        original: dict,
        roundtripped: dict,
        prefix: str = "",
    ) -> list[str]:
        """Recursively find all paths where *original* and *roundtripped* differ.

        Args:
            original: The original (or left-side) dict.
            roundtripped: The round-tripped (or right-side) dict.
            prefix: Dot-separated path prefix for nested keys.

        Returns:
            Sorted list of dot-separated field paths that differ.
        """
        drifted: list[str] = []
        all_keys = set(original.keys()) | set(roundtripped.keys())

        for key in sorted(all_keys):
            if key in self.IGNORED_KEYS:
                continue
            path = f"{prefix}.{key}".lstrip(".") if prefix else key
            orig_val = original.get(key)
            rt_val = roundtripped.get(key)

            if orig_val is None and rt_val is None:
                continue

            if isinstance(orig_val, dict) and isinstance(rt_val, dict):
                # Recurse into nested dicts.
                nested = self._compare_fields(orig_val, rt_val, prefix=path)
                drifted.extend(nested)
            elif orig_val != rt_val:
                drifted.append(path)

        return drifted

    # ------------------------------------------------------------------
    # Nested value accessor
    # ------------------------------------------------------------------

    @staticmethod
    def _get_nested(config: dict, dot_path: str) -> Any:
        """Return the value at *dot_path* inside *config*, or ``None``.

        Args:
            config: The config dict to traverse.
            dot_path: Dot-separated path (e.g. ``"prompts.root"``).

        Returns:
            The value at that path, or ``None`` if any segment is missing.
        """
        parts = dot_path.split(".")
        current: Any = config
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
