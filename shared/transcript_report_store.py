"""Shared durable store for transcript intelligence reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.contracts import TranscriptReport as TranscriptReportContract

DEFAULT_TRANSCRIPT_REPORT_STORE_PATH = Path(".autoagent") / "intelligence_reports.json"


class TranscriptReportStore:
    """Persist transcript intelligence reports in a shared JSON store."""

    def __init__(self, path: str | Path = DEFAULT_TRANSCRIPT_REPORT_STORE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_reports(self) -> list[dict[str, Any]]:
        """Return stored reports ordered by recency."""
        payload = self._load()
        reports = list(payload.get("reports", {}).values())
        reports.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=True)
        return [self._wrap_report(self._normalize_report(report)) for report in reports]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Return one stored report by report ID."""
        payload = self._load()
        report = payload.get("reports", {}).get(report_id)
        if report is None:
            return None
        return self._wrap_report(self._normalize_report(report))

    def save_report(
        self,
        report: Any,
        *,
        archive_name: str | None = None,
        archive_base64: str | None = None,
    ) -> None:
        """Persist a transcript report payload.

        The archive fields are accepted for compatibility with existing callers,
        but the report itself is the durable source of truth.
        """

        payload = self._load()
        normalized_report = self._normalize_report(report, archive_name=archive_name)
        payload.setdefault("reports", {})
        payload["reports"][normalized_report["report_id"]] = normalized_report
        self._save(payload)

    def _load(self) -> dict[str, Any]:
        """Read the JSON payload from disk, or initialize an empty store."""
        if not self.path.exists():
            return {"reports": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        """Write the JSON payload back to disk."""
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _normalize_report(
        self,
        report: Any,
        *,
        archive_name: str | None = None,
    ) -> dict[str, Any]:
        """Convert a report-like object into the shared contract shape."""

        if hasattr(report, "to_dict"):
            payload = report.to_dict()
        elif isinstance(report, dict):
            payload = dict(report)
        else:
            raise TypeError("Transcript reports must be dict-like or expose to_dict()")

        if archive_name and not payload.get("archive_name"):
            payload["archive_name"] = archive_name

        contract = TranscriptReportContract.from_dict(payload)
        return contract.to_dict()

    @staticmethod
    def _wrap_report(report: dict[str, Any]) -> dict[str, Any]:
        """Expose both the legacy nested payload and the direct report fields."""

        wrapped = dict(report)
        wrapped["report"] = dict(report)
        return wrapped
