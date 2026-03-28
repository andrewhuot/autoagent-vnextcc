"""Pluggable connectors for ingesting business-outcome signals — P0-9."""

from __future__ import annotations

import csv
import io
import random
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from data.outcome_types import BusinessOutcome, OutcomeType


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class OutcomeConnector(ABC):
    """Abstract base class for all outcome data connectors."""

    @abstractmethod
    def connect(self, config: dict[str, Any]) -> bool:
        """Establish connection / validate config. Return True on success."""

    @abstractmethod
    def fetch_outcomes(self, since: str | None = None) -> list[BusinessOutcome]:
        """Fetch business outcomes, optionally filtered to records after *since*."""

    @abstractmethod
    def close(self) -> None:
        """Release any held resources."""


# ---------------------------------------------------------------------------
# CsatConnector — mock CSAT score adapter
# ---------------------------------------------------------------------------

class CsatConnector(OutcomeConnector):
    """Mock CSAT connector returning sample scored outcomes for testing."""

    _SAMPLE_TRACE_IDS = [
        "trace-001", "trace-002", "trace-003", "trace-004", "trace-005",
    ]

    def __init__(self) -> None:
        self._connected = False
        self._config: dict[str, Any] = {}

    def connect(self, config: dict[str, Any]) -> bool:
        self._config = config
        self._connected = True
        return True

    def fetch_outcomes(self, since: str | None = None) -> list[BusinessOutcome]:
        """Return synthetic CSAT scores in [1, 5] for a handful of trace IDs."""
        rng = random.Random(42)
        outcomes: list[BusinessOutcome] = []
        for trace_id in self._SAMPLE_TRACE_IDS:
            score = round(rng.uniform(1.0, 5.0), 2)
            outcomes.append(
                BusinessOutcome(
                    outcome_id=str(uuid.uuid4()),
                    trace_id=trace_id,
                    outcome_type=OutcomeType.CSAT,
                    outcome_value=score,
                    timestamp=_now_iso(),
                    confidence=1.0,
                    source="csat_mock",
                    delay_hours=0.0,
                    metadata={"survey_channel": "in-app"},
                )
            )
        return outcomes

    def close(self) -> None:
        self._connected = False


# ---------------------------------------------------------------------------
# WebhookConnector — stores outcomes pushed via HTTP webhook
# ---------------------------------------------------------------------------

class WebhookConnector(OutcomeConnector):
    """In-memory webhook receiver that accumulates posted outcomes."""

    def __init__(self) -> None:
        self._connected = False
        self._buffer: list[BusinessOutcome] = []

    def connect(self, config: dict[str, Any]) -> bool:
        self._connected = True
        return True

    def receive(self, outcome: BusinessOutcome) -> None:
        """Called by the webhook handler to push an outcome into the buffer."""
        self._buffer.append(outcome)

    def fetch_outcomes(self, since: str | None = None) -> list[BusinessOutcome]:
        """Drain and return all buffered outcomes (optionally filtered by timestamp)."""
        if since is None:
            results = list(self._buffer)
            self._buffer.clear()
            return results
        filtered = [o for o in self._buffer if o.timestamp >= since]
        self._buffer = [o for o in self._buffer if o.timestamp < since]
        return filtered

    def close(self) -> None:
        self._connected = False
        self._buffer.clear()


# ---------------------------------------------------------------------------
# CsvConnector — import outcomes from a CSV file
# ---------------------------------------------------------------------------

class CsvConnector(OutcomeConnector):
    """Import business outcomes from a CSV file.

    Expected columns (case-insensitive header row):
        trace_id, outcome_type, outcome_value, timestamp, confidence,
        source, delay_hours, [metadata_json]
    """

    _REQUIRED_COLS = {"trace_id", "outcome_type", "outcome_value"}

    def __init__(self) -> None:
        self._connected = False
        self._path: str = ""

    def connect(self, config: dict[str, Any]) -> bool:
        self._path = config.get("path", "")
        self._connected = bool(self._path)
        return self._connected

    def fetch_outcomes(self, since: str | None = None) -> list[BusinessOutcome]:
        """Read the CSV at the configured path and return parsed outcomes."""
        import json as _json

        if not self._path:
            return []

        outcomes: list[BusinessOutcome] = []
        with open(self._path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                normalised = {k.strip().lower(): v.strip() for k, v in row.items()}
                missing = self._REQUIRED_COLS - set(normalised.keys())
                if missing:
                    continue  # skip malformed rows
                try:
                    outcome_type = OutcomeType(normalised["outcome_type"].upper())
                except ValueError:
                    outcome_type = OutcomeType.CUSTOM
                raw_meta = normalised.get("metadata_json", "{}")
                try:
                    meta = _json.loads(raw_meta) if raw_meta else {}
                except Exception:
                    meta = {}
                outcome = BusinessOutcome(
                    outcome_id=str(uuid.uuid4()),
                    trace_id=normalised.get("trace_id", ""),
                    outcome_type=outcome_type,
                    outcome_value=float(normalised.get("outcome_value", 0)),
                    timestamp=normalised.get("timestamp", _now_iso()),
                    confidence=float(normalised.get("confidence", 1.0)),
                    source=normalised.get("source", "csv"),
                    delay_hours=float(normalised.get("delay_hours", 0.0)),
                    metadata=meta,
                )
                if since is None or outcome.timestamp >= since:
                    outcomes.append(outcome)
        return outcomes

    def fetch_from_string(self, csv_content: str, since: str | None = None) -> list[BusinessOutcome]:
        """Parse outcomes from a CSV string (used by import_from_csv service)."""
        import json as _json

        outcomes: list[BusinessOutcome] = []
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            normalised = {k.strip().lower(): v.strip() for k, v in row.items()}
            missing = self._REQUIRED_COLS - set(normalised.keys())
            if missing:
                continue
            try:
                outcome_type = OutcomeType(normalised["outcome_type"].upper())
            except ValueError:
                outcome_type = OutcomeType.CUSTOM
            raw_meta = normalised.get("metadata_json", "{}")
            try:
                meta = _json.loads(raw_meta) if raw_meta else {}
            except Exception:
                meta = {}
            outcome = BusinessOutcome(
                outcome_id=str(uuid.uuid4()),
                trace_id=normalised.get("trace_id", ""),
                outcome_type=outcome_type,
                outcome_value=float(normalised.get("outcome_value", 0)),
                timestamp=normalised.get("timestamp", _now_iso()),
                confidence=float(normalised.get("confidence", 1.0)),
                source=normalised.get("source", "csv"),
                delay_hours=float(normalised.get("delay_hours", 0.0)),
                metadata=meta,
            )
            if since is None or outcome.timestamp >= since:
                outcomes.append(outcome)
        return outcomes

    def close(self) -> None:
        self._connected = False


# ---------------------------------------------------------------------------
# ConnectorRegistry
# ---------------------------------------------------------------------------

class ConnectorRegistry:
    """Registry mapping connector names to connector classes."""

    def __init__(self) -> None:
        self._registry: dict[str, type[OutcomeConnector]] = {}

    def register(self, name: str, connector_cls: type[OutcomeConnector]) -> None:
        """Register a connector class under *name*."""
        self._registry[name] = connector_cls

    def get(self, name: str) -> type[OutcomeConnector] | None:
        """Return the connector class for *name*, or None if not found."""
        return self._registry.get(name)

    def list_connectors(self) -> list[str]:
        """Return sorted list of registered connector names."""
        return sorted(self._registry.keys())


# Default registry with built-in connectors pre-registered
default_registry = ConnectorRegistry()
default_registry.register("csat", CsatConnector)
default_registry.register("webhook", WebhookConnector)
default_registry.register("csv", CsvConnector)
