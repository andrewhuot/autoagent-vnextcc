"""Export training data in SFT, DPO, and Vertex AI tuning formats."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any


class TrainingDataExporter:
    """Convert internal trace / pair records to fine-tuning dataset files."""

    # ------------------------------------------------------------------
    # SFT
    # ------------------------------------------------------------------

    def export_sft(self, traces: list[dict[str, Any]], output_path: str) -> str:
        """Write SFT JSONL from *traces* and return *output_path*.

        Trace keys: ``input`` (str), ``output`` (str).  Extra keys are
        preserved in a ``metadata`` field.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as fh:
            for trace in traces:
                input_text = trace.get("input", trace.get("input_text", ""))
                output_text = trace.get("output", trace.get("output_text", ""))
                record = {
                    "messages": [
                        {"role": "user", "content": str(input_text)},
                        {"role": "assistant", "content": str(output_text)},
                    ],
                    "metadata": {k: v for k, v in trace.items() if k not in {"input", "output", "input_text", "output_text"}},
                }
                fh.write(json.dumps(record) + "\n")
        return output_path

    # ------------------------------------------------------------------
    # DPO
    # ------------------------------------------------------------------

    def export_dpo(
        self,
        pairs: list[dict[str, Any]],
        output_path: str,
        format: str = "jsonl",
    ) -> str:
        """Write DPO pair JSONL/JSON and return *output_path*.

        Pair keys: ``input_text``, ``chosen``, ``rejected``.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        records = []
        for pair in pairs:
            record = {
                "prompt": pair.get("input_text", pair.get("prompt", "")),
                "chosen": pair.get("chosen", ""),
                "rejected": pair.get("rejected", ""),
            }
            records.append(record)

        with open(output_path, "w") as fh:
            if format == "json":
                json.dump(records, fh, indent=2)
            else:
                for record in records:
                    fh.write(json.dumps(record) + "\n")
        return output_path

    # ------------------------------------------------------------------
    # Vertex AI tuning
    # ------------------------------------------------------------------

    def export_vertex_tuning(self, data: list[dict[str, Any]], output_path: str) -> str:
        """Write Vertex AI supervised tuning JSONL and return *output_path*.

        Each record must have ``input_text`` and ``output_text``.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as fh:
            for item in data:
                record = {
                    "input_text": item.get("input_text", item.get("input", "")),
                    "output_text": item.get("output_text", item.get("output", "")),
                }
                fh.write(json.dumps(record) + "\n")
        return output_path
