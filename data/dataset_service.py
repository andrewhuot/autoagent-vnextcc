"""High-level dataset service: import, split, quality metrics, and export."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from data.dataset_store import DatasetStore
from data.dataset_types import (
    DatasetInfo,
    DatasetQualityMetrics,
    DatasetRow,
    DatasetSplit,
    DatasetVersion,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatasetService:
    """High-level service that orchestrates dataset lifecycle operations.

    Wraps ``DatasetStore`` with domain logic for:
    - Importing from traces, eval cases, and CSV files
    - Configuring train/eval/test splits
    - Computing quality metrics (coverage, staleness, balance)
    - Exporting snapshots to JSON
    """

    def __init__(self, store: Optional[DatasetStore] = None) -> None:
        self.store = store or DatasetStore()

    # ------------------------------------------------------------------
    # Create / read
    # ------------------------------------------------------------------

    def create(self, name: str, description: str = "") -> DatasetInfo:
        """Create a new empty dataset and return its DatasetInfo."""
        raw = self.store.create_dataset(name=name, description=description)
        return DatasetInfo(
            dataset_id=raw["dataset_id"],
            name=raw["name"],
            description=raw["description"],
            current_version=raw["current_version"],
            created_at=raw["created_at"],
        )

    def get(self, dataset_id: str) -> Optional[DatasetInfo]:
        """Return DatasetInfo for a dataset, or None if not found."""
        raw = self.store.get_dataset(dataset_id)
        if not raw:
            return None
        versions = self.store.list_versions(dataset_id)
        version_ids = [v["version_id"] for v in versions]
        # Determine unique splits present
        all_rows = self.store.get_rows(dataset_id)
        splits = sorted({r.get("split", "tuning") for r in all_rows})
        return DatasetInfo(
            dataset_id=raw["dataset_id"],
            name=raw["name"],
            description=raw["description"],
            current_version=raw["current_version"],
            created_at=raw["created_at"],
            versions=version_ids,
            splits=splits,
        )

    def list_datasets(self) -> list[DatasetInfo]:
        """Return all datasets as DatasetInfo objects."""
        raws = self.store.list_datasets()
        return [
            DatasetInfo(
                dataset_id=r["dataset_id"],
                name=r["name"],
                description=r["description"],
                current_version=r["current_version"],
                created_at=r["created_at"],
            )
            for r in raws
        ]

    # ------------------------------------------------------------------
    # Import helpers
    # ------------------------------------------------------------------

    def import_from_traces(
        self, dataset_id: str, traces: list[dict[str, Any]]
    ) -> int:
        """Import rows derived from agent traces.

        Each trace dict should have at least ``input`` (or ``user_message``
        / ``task``) and optionally ``expected_response`` (or
        ``reference_answer``).

        Returns the number of rows added.
        """
        rows: list[dict[str, Any]] = []
        for t in traces:
            input_text = (
                t.get("input")
                or t.get("user_message")
                or t.get("task")
                or ""
            )
            expected = (
                t.get("expected_response")
                or t.get("reference_answer")
                or t.get("output")
                or ""
            )
            row = DatasetRow(
                input=input_text,
                expected_response=expected,
                trajectory_expectations=t.get("trajectory_expectations", []),
                tool_constraints=t.get(
                    "tool_constraints", {"must_call": [], "must_not_call": []}
                ),
                safety_labels=t.get("safety_labels", []),
                slice_tags=t.get("slice_tags", {}),
                cost_budget=t.get("cost_budget"),
                latency_budget_ms=t.get("latency_budget_ms"),
                business_outcome_labels=t.get("business_outcome_labels", {}),
                category=t.get("category", "general"),
                split=t.get("split", "tuning"),
                metadata={
                    "source": "trace",
                    "trace_id": t.get("trace_id", ""),
                    **t.get("metadata", {}),
                },
            )
            rows.append(row.to_dict())
        if rows:
            self.store.add_rows(dataset_id, rows)
        return len(rows)

    def import_from_eval_cases(
        self, dataset_id: str, cases: list[dict[str, Any]]
    ) -> int:
        """Import rows derived from EvalCase dicts.

        Accepts the ``to_dict()`` output of ``EvalCase`` objects (``task``
        field maps to ``input``, ``reference_answer`` to
        ``expected_response``).

        Returns the number of rows added.
        """
        rows: list[dict[str, Any]] = []
        for c in cases:
            input_text = c.get("task") or c.get("input") or ""
            expected = (
                c.get("reference_answer")
                or c.get("expected_response")
                or c.get("expected_behavior")
                or ""
            )
            tool_constraints: dict[str, Any] = {"must_call": [], "must_not_call": []}
            if c.get("expected_tool"):
                tool_constraints["must_call"] = [c["expected_tool"]]

            safety_labels: list[str] = []
            if c.get("safety_probe"):
                safety_labels.append("safety_probe")

            row = DatasetRow(
                input=input_text,
                expected_response=expected,
                trajectory_expectations=[],
                tool_constraints=tool_constraints,
                safety_labels=safety_labels,
                slice_tags={
                    k: str(v)
                    for k, v in {
                        "suite_type": c.get("suite_type", ""),
                        "root_cause_tag": c.get("root_cause_tag", ""),
                    }.items()
                    if v
                },
                cost_budget=None,
                latency_budget_ms=None,
                business_outcome_labels={
                    "business_impact": c.get("business_impact", 1.0)
                },
                category=c.get("category", "general"),
                split=c.get("split", "tuning"),
                metadata={
                    "source": "eval_case",
                    "case_id": c.get("case_id", ""),
                    **c.get("metadata", {}),
                },
            )
            rows.append(row.to_dict())
        if rows:
            self.store.add_rows(dataset_id, rows)
        return len(rows)

    def import_from_csv(self, dataset_id: str, csv_path: str) -> int:
        """Import rows from a CSV file.

        Required column: ``input``.
        Optional columns: ``expected_response``, ``category``, ``split``,
        ``safety_labels`` (comma-separated), ``cost_budget``,
        ``latency_budget_ms``.

        Returns the number of rows added.
        """
        rows: list[dict[str, Any]] = []
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for record in reader:
                safety_raw = record.get("safety_labels", "")
                safety_labels = (
                    [s.strip() for s in safety_raw.split(",") if s.strip()]
                    if safety_raw
                    else []
                )
                cost_budget_raw = record.get("cost_budget", "")
                cost_budget: Optional[float] = (
                    float(cost_budget_raw) if cost_budget_raw else None
                )
                latency_raw = record.get("latency_budget_ms", "")
                latency_budget: Optional[float] = (
                    float(latency_raw) if latency_raw else None
                )
                row = DatasetRow(
                    input=record.get("input", ""),
                    expected_response=record.get("expected_response", ""),
                    safety_labels=safety_labels,
                    category=record.get("category", "general"),
                    split=record.get("split", "tuning"),
                    cost_budget=cost_budget,
                    latency_budget_ms=latency_budget,
                    metadata={"source": "csv", "csv_path": csv_path},
                )
                rows.append(row.to_dict())
        if rows:
            self.store.add_rows(dataset_id, rows)
        return len(rows)

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def create_version(
        self,
        dataset_id: str,
        description: str = "",
    ) -> DatasetVersion:
        """Freeze current unversioned rows into an immutable snapshot."""
        # Find the most recent version to use as parent
        existing = self.store.list_versions(dataset_id)
        parent_id: Optional[str] = existing[0]["version_id"] if existing else None

        raw = self.store.create_version(
            dataset_id=dataset_id,
            description=description,
            parent_version_id=parent_id,
        )
        return DatasetVersion.from_dict(raw)

    def get_version(self, version_id: str) -> Optional[DatasetVersion]:
        """Return a DatasetVersion by its version_id."""
        raw = self.store.get_version(version_id)
        return DatasetVersion.from_dict(raw) if raw else None

    def list_versions(self, dataset_id: str) -> list[DatasetVersion]:
        """Return all versions for a dataset, newest first."""
        return [DatasetVersion.from_dict(v) for v in self.store.list_versions(dataset_id)]

    # ------------------------------------------------------------------
    # Split management
    # ------------------------------------------------------------------

    def get_split(
        self,
        dataset_id: str,
        version_id: Optional[str],
        split: Optional[str] = None,
    ) -> list[DatasetRow]:
        """Return rows for a given version and optional split name."""
        raw_rows = self.store.get_rows(
            dataset_id, version_id=version_id, split=split
        )
        return [DatasetRow.from_dict(r) for r in raw_rows]

    def configure_splits(
        self,
        dataset_id: str,
        splits: dict[str, float],
    ) -> list[DatasetSplit]:
        """Re-assign split tags to unversioned rows according to percentages.

        ``splits`` maps split name -> fraction (values should sum to ≤1.0).
        Rows are assigned deterministically by their insertion order.
        Returns a list of DatasetSplit objects describing the outcome.
        """
        # Fetch all unversioned rows (version_id == '')
        all_rows = self.store.get_rows(dataset_id, version_id="")
        if not all_rows:
            # Fall back to all rows regardless of version
            all_rows = self.store.get_rows(dataset_id)

        total = len(all_rows)
        if total == 0:
            return []

        import sqlite3

        result_splits: list[DatasetSplit] = []
        offset = 0

        for split_name, fraction in splits.items():
            count = round(total * fraction)
            slice_rows = all_rows[offset : offset + count]
            row_ids = [r["_row_id"] for r in slice_rows if "_row_id" in r]

            # Update split tag in DB
            if row_ids:
                with sqlite3.connect(self.store.db_path) as conn:
                    placeholders = ",".join("?" * len(row_ids))
                    conn.execute(
                        f"UPDATE dataset_rows SET split = ? WHERE id IN ({placeholders})",
                        [split_name, *row_ids],
                    )
                    conn.commit()

            result_splits.append(
                DatasetSplit(
                    split_name=split_name,
                    row_ids=row_ids,
                    percentage=fraction,
                )
            )
            offset += count

        return result_splits

    # ------------------------------------------------------------------
    # Quality metrics
    # ------------------------------------------------------------------

    def compute_quality_metrics(self, dataset_id: str) -> DatasetQualityMetrics:
        """Compute coverage, staleness, balance, and failure mode distribution."""
        info = self.store.get_dataset(dataset_id)
        if not info:
            return DatasetQualityMetrics()

        all_rows = self.store.get_rows(dataset_id)
        total = len(all_rows)
        if total == 0:
            return DatasetQualityMetrics(total_rows=0)

        # Balance: fraction of rows per category
        category_counts: dict[str, int] = {}
        split_counts: dict[str, int] = {}
        failure_modes: dict[str, int] = {}

        for r in all_rows:
            cat = r.get("category", "general")
            category_counts[cat] = category_counts.get(cat, 0) + 1

            sp = r.get("split", "tuning")
            split_counts[sp] = split_counts.get(sp, 0) + 1

            for label in r.get("safety_labels", []):
                failure_modes[label] = failure_modes.get(label, 0) + 1

        balance = {cat: count / total for cat, count in category_counts.items()}

        # Coverage: fraction of categories that have > 0 rows (naive measure)
        coverage = len(category_counts) / max(len(category_counts), 1)

        # Staleness: days since dataset was created
        created_at_str = info.get("created_at", "")
        staleness_days = 0.0
        if created_at_str:
            try:
                created_dt = datetime.fromisoformat(created_at_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - created_dt
                staleness_days = delta.total_seconds() / 86400.0
            except ValueError:
                pass

        failure_mode_distribution = {
            k: v / total for k, v in failure_modes.items()
        }

        return DatasetQualityMetrics(
            coverage=coverage,
            staleness_days=staleness_days,
            balance=balance,
            total_rows=total,
            failure_mode_distribution=failure_mode_distribution,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_to_json(
        self,
        dataset_id: str,
        version_id: Optional[str],
        output_path: str,
    ) -> str:
        """Export all rows (optionally scoped to a version) to a JSON file.

        Returns the resolved output path.
        """
        rows = self.store.get_rows(dataset_id, version_id=version_id)
        ds_info = self.store.get_dataset(dataset_id)

        export_doc = {
            "dataset_id": dataset_id,
            "name": ds_info.get("name", "") if ds_info else "",
            "version_id": version_id,
            "exported_at": _now_iso(),
            "row_count": len(rows),
            "rows": rows,
        }

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(export_doc, fh, indent=2, default=str)

        return output_path

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self, dataset_id: str) -> dict[str, Any]:
        """Return a summary dict for a dataset including quality metrics."""
        info = self.store.get_dataset(dataset_id)
        if not info:
            return {"error": "dataset not found"}

        versions = self.store.list_versions(dataset_id)
        total_rows = self.store.count_rows(dataset_id)
        metrics = self.compute_quality_metrics(dataset_id)

        # Per-split row counts
        split_counts: dict[str, int] = {}
        all_rows = self.store.get_rows(dataset_id)
        for r in all_rows:
            sp = r.get("split", "tuning")
            split_counts[sp] = split_counts.get(sp, 0) + 1

        return {
            "dataset_id": dataset_id,
            "name": info.get("name", ""),
            "description": info.get("description", ""),
            "current_version": info.get("current_version", ""),
            "created_at": info.get("created_at", ""),
            "total_rows": total_rows,
            "version_count": len(versions),
            "split_counts": split_counts,
            "quality_metrics": metrics.to_dict(),
        }
