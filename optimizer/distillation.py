"""Model distillation pipeline: trace collection, dataset preparation, Vertex export."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DistillationConfig:
    source_model: str
    target_model: str
    dataset_version: str
    max_examples: int = 1000
    temperature: float = 0.7


@dataclass
class DistillationResult:
    dataset_path: str
    examples_count: int
    source_model: str
    target_model: str
    estimated_cost_savings: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_path": self.dataset_path,
            "examples_count": self.examples_count,
            "source_model": self.source_model,
            "target_model": self.target_model,
            "estimated_cost_savings": self.estimated_cost_savings,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DistillationResult":
        return cls(
            dataset_path=data["dataset_path"],
            examples_count=data["examples_count"],
            source_model=data["source_model"],
            target_model=data["target_model"],
            estimated_cost_savings=data["estimated_cost_savings"],
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Cost model (rough token pricing per 1k tokens, input side)
# ---------------------------------------------------------------------------

_MODEL_COST_PER_1K: dict[str, float] = {
    "gemini-2.0-flash": 0.00015,
    "gemini-1.5-pro": 0.00125,
    "gemini-1.5-flash": 0.000075,
    "claude-3-5-sonnet": 0.003,
    "claude-3-haiku": 0.00025,
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class DistillationPipeline:
    """Collect traces, package datasets, and estimate distillation savings."""

    # ------------------------------------------------------------------
    # Trace collection
    # ------------------------------------------------------------------

    def collect_traces(self, source_model: str, limit: int) -> list[dict[str, Any]]:
        """Return up to *limit* trace records attributed to *source_model*.

        In a real deployment this queries the trace store / replay DB.
        Here we read from the local replay.db if present, otherwise return
        an empty list so callers can reason about the structure.
        """
        traces: list[dict[str, Any]] = []
        replay_db = "replay.db"
        if os.path.exists(replay_db):
            import sqlite3

            try:
                with sqlite3.connect(replay_db) as conn:
                    rows = conn.execute(
                        "SELECT * FROM replays WHERE model = ? LIMIT ?",
                        (source_model, limit),
                    ).fetchall()
                    for row in rows:
                        traces.append({"raw": row, "model": source_model})
            except Exception:
                pass
        return traces[:limit]

    # ------------------------------------------------------------------
    # Dataset preparation
    # ------------------------------------------------------------------

    def prepare_dataset(self, traces: list[dict[str, Any]], config: DistillationConfig) -> str:
        """Convert raw traces to a JSONL SFT dataset and return the file path."""
        os.makedirs(".autoagent", exist_ok=True)
        out_path = f".autoagent/distill_{config.dataset_version}_{uuid.uuid4().hex[:8]}.jsonl"

        limited = traces[: config.max_examples]
        with open(out_path, "w") as fh:
            for trace in limited:
                input_text = trace.get("input", trace.get("raw", ""))
                output_text = trace.get("output", "")
                record = {
                    "messages": [
                        {"role": "user", "content": str(input_text)},
                        {"role": "assistant", "content": str(output_text)},
                    ],
                    "source_model": config.source_model,
                    "target_model": config.target_model,
                    "temperature": config.temperature,
                }
                fh.write(json.dumps(record) + "\n")

        return out_path

    # ------------------------------------------------------------------
    # Vertex export
    # ------------------------------------------------------------------

    def export_for_vertex(self, dataset_path: str, output_path: str) -> str:
        """Reformat a JSONL dataset into Vertex AI fine-tuning format."""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        converted: list[str] = []
        with open(dataset_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                messages = record.get("messages", [])
                # Vertex supervised tuning expects {"input_text": ..., "output_text": ...}
                input_parts = [m["content"] for m in messages if m.get("role") == "user"]
                output_parts = [m["content"] for m in messages if m.get("role") == "assistant"]
                vertex_record = {
                    "input_text": " ".join(input_parts),
                    "output_text": " ".join(output_parts),
                }
                converted.append(json.dumps(vertex_record))

        with open(output_path, "w") as fh:
            fh.write("\n".join(converted))

        return output_path

    # ------------------------------------------------------------------
    # Savings estimate
    # ------------------------------------------------------------------

    def estimate_savings(self, source_model: str, target_model: str) -> dict[str, Any]:
        """Estimate cost savings from switching *source_model* to *target_model*."""
        src_cost = _MODEL_COST_PER_1K.get(source_model, 0.001)
        tgt_cost = _MODEL_COST_PER_1K.get(target_model, 0.0001)
        savings_pct = max(0.0, (src_cost - tgt_cost) / src_cost * 100) if src_cost else 0.0
        return {
            "source_model": source_model,
            "target_model": target_model,
            "source_cost_per_1k": src_cost,
            "target_cost_per_1k": tgt_cost,
            "absolute_savings_per_1k": max(0.0, src_cost - tgt_cost),
            "savings_pct": round(savings_pct, 2),
            "estimated_at": datetime.now(timezone.utc).isoformat(),
        }
