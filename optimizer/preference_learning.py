"""Preference learning pipeline: collect DPO pairs, export to multiple formats."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PreferencePair:
    input_text: str
    chosen: str
    rejected: str
    source: str = "human_review"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_text": self.input_text,
            "chosen": self.chosen,
            "rejected": self.rejected,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreferencePair":
        return cls(
            input_text=data["input_text"],
            chosen=data["chosen"],
            rejected=data["rejected"],
            source=data.get("source", "human_review"),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PreferenceLearningPipeline:
    """Build DPO datasets from human reviews and automated experiments."""

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def collect_pairs_from_reviews(self, reviews: list[dict[str, Any]]) -> list[PreferencePair]:
        """Extract preference pairs from human review records.

        Expected review keys: ``input``, ``preferred_output``, ``rejected_output``.
        Unknown reviews are silently skipped.
        """
        pairs: list[PreferencePair] = []
        for review in reviews:
            inp = review.get("input") or review.get("input_text", "")
            chosen = review.get("preferred_output") or review.get("chosen", "")
            rejected = review.get("rejected_output") or review.get("rejected", "")
            if inp and chosen and rejected:
                pairs.append(
                    PreferencePair(
                        input_text=inp,
                        chosen=chosen,
                        rejected=rejected,
                        source="human_review",
                        metadata={k: v for k, v in review.items() if k not in {"input", "preferred_output", "rejected_output", "input_text", "chosen", "rejected"}},
                    )
                )
        return pairs

    def collect_pairs_from_experiments(self, experiments: list[dict[str, Any]]) -> list[PreferencePair]:
        """Build pairs from A/B experiment results.

        Expected experiment keys: ``prompt``, ``control_output``, ``treatment_output``,
        ``winner`` ("control" | "treatment").
        """
        pairs: list[PreferencePair] = []
        for exp in experiments:
            prompt = exp.get("prompt", "")
            control = exp.get("control_output", "")
            treatment = exp.get("treatment_output", "")
            winner = exp.get("winner", "")
            if not (prompt and control and treatment and winner):
                continue
            if winner == "treatment":
                chosen, rejected = treatment, control
            else:
                chosen, rejected = control, treatment
            pairs.append(
                PreferencePair(
                    input_text=prompt,
                    chosen=chosen,
                    rejected=rejected,
                    source="experiment",
                    metadata={"experiment_id": exp.get("experiment_id", ""), "winner": winner},
                )
            )
        return pairs

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_dpo_dataset(self, pairs: list[PreferencePair], format: str = "vertex") -> str:
        """Write DPO pairs to disk and return the output file path."""
        os.makedirs(".autoagent", exist_ok=True)
        out_path = f".autoagent/dpo_{format}_{uuid.uuid4().hex[:8]}.jsonl"
        with open(out_path, "w") as fh:
            for pair in pairs:
                if format == "vertex":
                    record = {
                        "input_text": pair.input_text,
                        "candidate_0": pair.chosen,
                        "candidate_1": pair.rejected,
                        "choice": 0,
                    }
                else:
                    record = pair.to_dict()
                fh.write(json.dumps(record) + "\n")
        return out_path

    def export_openai_format(self, pairs: list[PreferencePair]) -> str:
        """Write pairs in OpenAI DPO JSONL format and return the file path."""
        os.makedirs(".autoagent", exist_ok=True)
        out_path = f".autoagent/dpo_openai_{uuid.uuid4().hex[:8]}.jsonl"
        with open(out_path, "w") as fh:
            for pair in pairs:
                record = {
                    "prompt": pair.input_text,
                    "chosen": [{"role": "assistant", "content": pair.chosen}],
                    "rejected": [{"role": "assistant", "content": pair.rejected}],
                }
                fh.write(json.dumps(record) + "\n")
        return out_path
