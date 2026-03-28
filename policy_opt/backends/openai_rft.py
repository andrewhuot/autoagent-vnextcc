"""OpenAI Reinforcement Fine-Tuning (RFT) backend adapter."""

from __future__ import annotations

import json
from typing import Any

from policy_opt.backends.base import TrainingBackend, register_backend
from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


@register_backend("openai_rft")
class OpenAIRFTBackend(TrainingBackend):
    """Backend for OpenAI's Reinforcement Fine-Tuning API.

    Supports verifier-mode training using OpenAI's RLVR pipeline.
    Each training example must include a conversation in ``messages``
    format plus a ``grader`` specification that the API uses to score
    model completions during the RL loop.
    """

    name = "openai_rft"
    supported_modes = [TrainingMode.verifier]

    # Required top-level fields per training example.
    _REQUIRED_FIELDS = {"messages", "grader"}

    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate JSONL dataset for OpenAI RFT format.

        Each line must be valid JSON and contain both ``messages`` (a list)
        and ``grader`` (a dict describing the reward function).
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
                    if "messages" in record and not isinstance(record["messages"], list):
                        errors.append(f"Line {lineno}: 'messages' must be a list")
                    if "grader" in record and not isinstance(record["grader"], dict):
                        errors.append(f"Line {lineno}: 'grader' must be a dict")
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def start_training(self, job: TrainingJob) -> str:
        """Submit an RFT fine-tuning job to the OpenAI API.

        TODO: Implement using the openai SDK once API keys are available.
          client = openai.OpenAI(api_key=...)
          file_id = client.files.create(file=open(job.dataset_path), purpose="fine-tune").id
          ft = client.fine_tuning.jobs.create(
              training_file=file_id,
              model=job.config.get("base_model", "gpt-4o-mini"),
              method={"type": "reinforcement", "grader": job.reward_spec},
              hyperparameters=job.config.get("hyperparameters", {}),
          )
          return ft.id
        """
        raise NotImplementedError(
            "OpenAI RFT start_training requires OPENAI_API_KEY — not yet wired up."
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
            "OpenAI RFT check_status requires OPENAI_API_KEY — not yet wired up."
        )

    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Retrieve the fine-tuned model ID and training metrics.

        TODO: client.fine_tuning.jobs.retrieve(provider_job_id)
          return {"model_id": job.fine_tuned_model, "metrics": job.result_files}
        """
        raise NotImplementedError(
            "OpenAI RFT get_result requires OPENAI_API_KEY — not yet wired up."
        )

    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a queued or running RFT job.

        TODO: client.fine_tuning.jobs.cancel(provider_job_id)
        """
        raise NotImplementedError(
            "OpenAI RFT cancel requires OPENAI_API_KEY — not yet wired up."
        )
