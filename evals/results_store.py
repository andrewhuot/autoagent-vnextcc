"""SQLite-backed storage for structured eval results and annotations."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from pathlib import Path

from evals.results_model import Annotation, EvalResultSet, ExampleResult, GraderScore


class EvalResultsStore:
    """Persist structured eval results with query and export helpers."""

    def __init__(self, db_path: str = ".agentlab/eval_results.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a row-friendly SQLite connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create required tables if they do not exist yet."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    config_snapshot TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_examples (
                    run_id TEXT NOT NULL,
                    example_id TEXT NOT NULL,
                    example_index INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    input_json TEXT NOT NULL,
                    expected_json TEXT,
                    actual_json TEXT NOT NULL,
                    failure_reasons TEXT NOT NULL,
                    component_attributions TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (run_id, example_id)
                )
                """
            )
            example_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(result_examples)").fetchall()
            }
            if "component_attributions" not in example_columns:
                conn.execute(
                    "ALTER TABLE result_examples "
                    "ADD COLUMN component_attributions TEXT NOT NULL DEFAULT '[]'"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_scores (
                    run_id TEXT NOT NULL,
                    example_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    PRIMARY KEY (run_id, example_id, metric)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_annotations (
                    annotation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    example_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    score_override REAL
                )
                """
            )
            conn.commit()

    def save(self, result_set: EvalResultSet) -> None:
        """Persist a complete structured result set."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO result_runs (run_id, created_at, mode, config_snapshot, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result_set.run_id,
                    result_set.timestamp,
                    result_set.mode,
                    json.dumps(result_set.config_snapshot),
                    json.dumps(result_set.summary.to_dict()),
                ),
            )
            conn.execute("DELETE FROM result_examples WHERE run_id = ?", (result_set.run_id,))
            conn.execute("DELETE FROM result_scores WHERE run_id = ?", (result_set.run_id,))
            conn.execute("DELETE FROM result_annotations WHERE run_id = ?", (result_set.run_id,))

            for index, example in enumerate(result_set.examples):
                conn.execute(
                    """
                    INSERT INTO result_examples (
                        run_id,
                        example_id,
                        example_index,
                        category,
                        passed,
                        input_json,
                        expected_json,
                        actual_json,
                        failure_reasons,
                        component_attributions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_set.run_id,
                        example.example_id,
                        index,
                        example.category,
                        1 if example.passed else 0,
                        json.dumps(example.input),
                        json.dumps(example.expected) if example.expected is not None else None,
                        json.dumps(example.actual),
                        json.dumps(example.failure_reasons),
                        json.dumps(example.component_attributions),
                    ),
                )
                for metric_name, metric in example.scores.items():
                    conn.execute(
                        """
                        INSERT INTO result_scores (run_id, example_id, metric, value, reasoning)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            result_set.run_id,
                            example.example_id,
                            metric_name,
                            metric.value,
                            metric.reasoning,
                        ),
                    )
                for annotation in example.annotations:
                    self._insert_annotation(conn, result_set.run_id, example.example_id, annotation)
            conn.commit()

    def get_run(self, run_id: str) -> EvalResultSet | None:
        """Load one full structured run with examples, scores, and annotations."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, created_at, mode, config_snapshot, summary FROM result_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None

        examples, _total = self.get_examples(run_id, page=1, page_size=100000)
        return EvalResultSet(
            run_id=row["run_id"],
            timestamp=row["created_at"],
            mode=row["mode"],
            config_snapshot=json.loads(row["config_snapshot"]),
            summary=EvalResultSet.from_dict(
                {
                    "run_id": row["run_id"],
                    "timestamp": row["created_at"],
                    "mode": row["mode"],
                    "config_snapshot": json.loads(row["config_snapshot"]),
                    "summary": json.loads(row["summary"]),
                    "examples": [],
                }
            ).summary,
            examples=examples,
        )

    def list_runs(
        self,
        *,
        limit: int = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, object]]:
        """List recent result runs with summary metadata."""
        query = """
            SELECT run_id, created_at, mode, config_snapshot, summary
            FROM result_runs
        """
        clauses = []
        params: list[object] = []
        if start is not None:
            clauses.append("created_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("created_at <= ?")
            params.append(end)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        output = []
        for row in rows:
            summary = json.loads(row["summary"])
            output.append(
                {
                    "run_id": row["run_id"],
                    "timestamp": row["created_at"],
                    "mode": row["mode"],
                    "config_snapshot": json.loads(row["config_snapshot"]),
                    "summary": summary,
                }
            )
        return output

    def latest_run_id(self) -> str | None:
        """Return the most recent run id, or None when the store is empty."""
        runs = self.list_runs(limit=1)
        if not runs:
            return None
        return str(runs[0]["run_id"])

    def latest_run(self) -> EvalResultSet | None:
        """Return the most recent stored run with full example detail."""
        run_id = self.latest_run_id()
        if run_id is None:
            return None
        return self.get_run(run_id)

    def get_summary(self, run_id: str):
        """Return just the stored summary for one run."""
        result_set = self.get_run(run_id)
        if result_set is None:
            return None
        return result_set.summary

    def get_examples(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        passed: bool | None = None,
        metric: str | None = None,
        below: float | None = None,
        above: float | None = None,
    ) -> tuple[list[ExampleResult], int]:
        """Return a paginated, filterable example slice for one run."""
        where_clauses = ["e.run_id = ?"]
        params: list[object] = [run_id]
        join = ""
        if passed is not None:
            where_clauses.append("e.passed = ?")
            params.append(1 if passed else 0)
        if metric is not None:
            join = " JOIN result_scores s ON s.run_id = e.run_id AND s.example_id = e.example_id "
            where_clauses.append("s.metric = ?")
            params.append(metric)
            if below is not None:
                where_clauses.append("s.value < ?")
                params.append(below)
            if above is not None:
                where_clauses.append("s.value > ?")
                params.append(above)

        where_sql = " AND ".join(where_clauses)
        offset = max(0, page - 1) * max(1, page_size)
        query = (
            "SELECT DISTINCT e.example_id "
            "FROM result_examples e "
            f"{join}"
            f"WHERE {where_sql} "
            "ORDER BY e.example_index ASC LIMIT ? OFFSET ?"
        )
        count_query = (
            "SELECT COUNT(DISTINCT e.example_id) "
            "FROM result_examples e "
            f"{join}"
            f"WHERE {where_sql}"
        )

        with self._connect() as conn:
            total = int(conn.execute(count_query, params).fetchone()[0])
            rows = conn.execute(query, [*params, page_size, offset]).fetchall()

        examples = [self.get_example(run_id, row["example_id"]) for row in rows]
        return ([example for example in examples if example is not None], total)

    def get_example(self, run_id: str, example_id: str) -> ExampleResult | None:
        """Load one example result with scores and annotations."""
        with self._connect() as conn:
            example_row = conn.execute(
                """
                SELECT example_id, category, passed, input_json, expected_json, actual_json,
                       failure_reasons, component_attributions
                FROM result_examples
                WHERE run_id = ? AND example_id = ?
                """,
                (run_id, example_id),
            ).fetchone()
            if example_row is None:
                return None

            score_rows = conn.execute(
                """
                SELECT metric, value, reasoning
                FROM result_scores
                WHERE run_id = ? AND example_id = ?
                ORDER BY metric ASC
                """,
                (run_id, example_id),
            ).fetchall()
            annotation_rows = conn.execute(
                """
                SELECT author, timestamp, type, content, score_override
                FROM result_annotations
                WHERE run_id = ? AND example_id = ?
                ORDER BY timestamp ASC
                """,
                (run_id, example_id),
            ).fetchall()

        return ExampleResult(
            example_id=example_row["example_id"],
            input=json.loads(example_row["input_json"]),
            expected=json.loads(example_row["expected_json"]) if example_row["expected_json"] else None,
            actual=json.loads(example_row["actual_json"]),
            scores={
                row["metric"]: GraderScore(value=float(row["value"]), reasoning=row["reasoning"])
                for row in score_rows
            },
            passed=bool(example_row["passed"]),
            failure_reasons=json.loads(example_row["failure_reasons"]),
            component_attributions=json.loads(example_row["component_attributions"]),
            annotations=[
                Annotation(
                    author=row["author"],
                    timestamp=row["timestamp"],
                    type=row["type"],
                    content=row["content"],
                    score_override=float(row["score_override"]) if row["score_override"] is not None else None,
                )
                for row in annotation_rows
            ],
            category=example_row["category"],
        )

    def add_annotation(self, run_id: str, example_id: str, annotation: Annotation) -> None:
        """Append a new annotation to an example result."""
        with self._connect() as conn:
            self._insert_annotation(conn, run_id, example_id, annotation)
            conn.commit()

    def export_run(self, run_id: str, *, format: str = "json") -> str:
        """Export a run as JSON, CSV, or Markdown."""
        result_set = self.get_run(run_id)
        if result_set is None:
            raise ValueError(f"Run not found: {run_id}")

        normalized = format.lower().strip()
        if normalized == "json":
            return json.dumps(result_set.to_dict(), indent=2)
        if normalized == "csv":
            return self._export_csv(result_set)
        if normalized == "markdown":
            return self._export_markdown(result_set)
        raise ValueError(f"Unsupported export format: {format}")

    def diff_runs(self, baseline_run_id: str, candidate_run_id: str) -> dict[str, object]:
        """Compute a run-to-run diff keyed by example ID."""
        baseline = self.get_run(baseline_run_id)
        candidate = self.get_run(candidate_run_id)
        if baseline is None or candidate is None:
            raise ValueError("Both runs must exist to compute a diff")

        baseline_examples = {example.example_id: example for example in baseline.examples}
        candidate_examples = {example.example_id: example for example in candidate.examples}

        new_failures = 0
        new_passes = 0
        changed_examples: list[dict[str, object]] = []

        for example_id in sorted(set(baseline_examples) | set(candidate_examples)):
            before = baseline_examples.get(example_id)
            after = candidate_examples.get(example_id)
            if before is None or after is None:
                continue

            before_score = before.scores.get("composite", GraderScore(0.0)).value
            after_score = after.scores.get("composite", GraderScore(0.0)).value
            if before.passed and not after.passed:
                new_failures += 1
            if not before.passed and after.passed:
                new_passes += 1
            if before.passed != after.passed or abs(after_score - before_score) > 1e-9:
                changed_examples.append(
                    {
                        "example_id": example_id,
                        "before_passed": before.passed,
                        "after_passed": after.passed,
                        "score_delta": round(after_score - before_score, 4),
                    }
                )

        return {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "new_failures": new_failures,
            "new_passes": new_passes,
            "changed_examples": changed_examples,
        }

    def _insert_annotation(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        example_id: str,
        annotation: Annotation,
    ) -> None:
        """Insert one annotation row."""
        conn.execute(
            """
            INSERT INTO result_annotations (
                annotation_id,
                run_id,
                example_id,
                author,
                timestamp,
                type,
                content,
                score_override
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ann_{uuid.uuid4().hex[:12]}",
                run_id,
                example_id,
                annotation.author,
                annotation.timestamp,
                annotation.type,
                annotation.content,
                annotation.score_override,
            ),
        )

    def _export_csv(self, result_set: EvalResultSet) -> str:
        """Export one run as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["example_id", "passed", "category", "quality", "composite", "failure_reasons"])
        for example in result_set.examples:
            writer.writerow(
                [
                    example.example_id,
                    str(example.passed).lower(),
                    example.category,
                    example.scores.get("quality", GraderScore(0.0)).value,
                    example.scores.get("composite", GraderScore(0.0)).value,
                    "; ".join(example.failure_reasons),
                ]
            )
        return output.getvalue()

    def _export_markdown(self, result_set: EvalResultSet) -> str:
        """Export one run as a Markdown summary."""
        lines = [
            f"# Eval Results: {result_set.run_id}",
            "",
            f"- Timestamp: {result_set.timestamp}",
            f"- Mode: {result_set.mode}",
            f"- Passed: {result_set.summary.passed}/{result_set.summary.total}",
            "",
            "| example_id | passed | category | quality | composite |",
            "| --- | --- | --- | --- | --- |",
        ]
        for example in result_set.examples:
            lines.append(
                f"| {example.example_id} | {str(example.passed).lower()} | {example.category} | "
                f"{example.scores.get('quality', GraderScore(0.0)).value:.3f} | "
                f"{example.scores.get('composite', GraderScore(0.0)).value:.3f} |"
            )
        return "\n".join(lines)
