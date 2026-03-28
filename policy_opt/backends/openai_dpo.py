"""OpenAI Direct Preference Optimization (DPO) backend adapter."""

from __future__ import annotations

import json
from typing import Any

from policy_opt.backends.base import TrainingBackend, register_backend
from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


@register_backend("openai_dpo")
class OpenAIDPOBackend(TrainingBackend):
    """Backend for OpenAI's DPO / preference fine-tuning API.

    Supports preference-mode training. Each training example must supply
    a ``prompt`` (list of messages), a ``chosen`` response, and a
    ``rejected`` response so the model can learn human preference rankings.
    """

    name = "openai_dpo"
    supported_modes = [TrainingMode.preference]

    # Required top-level fields per training example.
    _REQUIRED_FIELDS = {"prompt", "chosen", "rejected"}

    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate JSONL dataset for OpenAI DPO format.

        Each line must be valid JSON with ``prompt`` (list), ``chosen``
        (dict with role/content), and ``rejected`` (dict with role/content).
        """
        errors: list[str] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for lineno, raw in enumerate(fh, start=1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        errors.append(f"Line {lineno}: invalid JSON — {exc}")
                        continue
                    for field in self._REQUIRED_FIELDS:
                        if field not in record:
                            errors.append(f"Line {lineno}: missing required field '{field}'")
                    if "prompt" in record and not isinstance(record["prompt"], list):
                        errors.append(f"Line {lineno}: 'prompt' must be a list of messages")
                    for resp_field in ("chosen", "rejected"):
                        if resp_field in record:
                            val = record[resp_field]
                            if not isinstance(val, dict) or "content" not in val:
                                errors.append(
                                    f"Line {lineno}: '{resp_field}' must be a dict with 'content'"
                                )
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def start_training(self, job: TrainingJob) -> str:
        """Submit a DPO fine-tuning job to the OpenAI API.

        TODO: Implement using the openai SDK once API keys are available.
          client = openai.OpenAI(api_key=...)
          file_id = client.files.create(file=open(job.dataset_path), purpose="fine-tune").id
          ft = client.fine_tuning.jobs.create(
              training_file=file_id,
              model=job.config.get("base_model", "gpt-4o-mini"),
              method={"type": "dpo", "dpo": {"beta": job.config.get("beta", 0.1)}},
              hyperparameters=job.config.get("hyperparameters", {}),
          )
          return ft.id
        """
        raise NotImplementedError(
            "OpenAI DPO start_training requires OPENAI_API_KEY — not yet wired up."
        )

    def check_status(self, provider_job_id: str) -> TrainingStatus:
        """Poll OpenAI fine-tuning job status.

        TODO: Map OpenAI statuses to TrainingStatus:
          "validating_files" / "queued" -> pending
          "running"                     -> running
          "succeeded"                   -> completed
          "failed"                      -> failed
          "cancelled"                   -> cancelled
        """
        raise NotImplementedError(
            "OpenAI DPO check_status requires OPENAI_API_KEY — not yet wired up."
        )

    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Retrieve the fine-tuned model ID and associated metrics.

        TODO: client.fine_tuning.jobs.retrieve(provider_job_id)
          return {"model_id": job.fine_tuned_model, "result_files": job.result_files}
        """
        raise NotImplementedError(
            "OpenAI DPO get_result requires OPENAI_API_KEY — not yet wired up."
        )

    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a queued or running DPO job.

        TODO: client.fine_tuning.jobs.cancel(provider_job_id)
        """
        raise NotImplementedError(
            "OpenAI DPO cancel requires OPENAI_API_KEY — not yet wired up."
        )
