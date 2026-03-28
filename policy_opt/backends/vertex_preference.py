"""Vertex AI Preference Tuning backend adapter."""

from __future__ import annotations

import json
from typing import Any

from policy_opt.backends.base import TrainingBackend, register_backend
from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


@register_backend("vertex_preference")
class VertexPreferenceBackend(TrainingBackend):
    """Backend for Vertex AI Preference (RLHF) Tuning.

    Supports preference-mode training. Each training example must provide
    ``input_text`` (the prompt), ``candidate_0`` and ``candidate_1`` (two
    competing responses), and ``choice`` (0 or 1 indicating the preferred
    response). This maps to Vertex AI's RLHF tuning JSONL schema.
    """

    name = "vertex_preference"
    supported_modes = [TrainingMode.preference]

    # Required top-level fields per training example.
    _REQUIRED_FIELDS = {"input_text", "candidate_0", "candidate_1", "choice"}

    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate JSONL dataset for Vertex AI Preference Tuning format.

        Each line must be valid JSON with ``input_text`` (str), ``candidate_0``
        (str), ``candidate_1`` (str), and ``choice`` (int, 0 or 1).
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
                    for text_field in ("input_text", "candidate_0", "candidate_1"):
                        if text_field in record:
                            if not isinstance(record[text_field], str):
                                errors.append(f"Line {lineno}: '{text_field}' must be a string")
                            elif not record[text_field].strip():
                                errors.append(f"Line {lineno}: '{text_field}' must not be empty")
                    if "choice" in record:
                        if record["choice"] not in (0, 1):
                            errors.append(
                                f"Line {lineno}: 'choice' must be 0 or 1, got {record['choice']!r}"
                            )
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def start_training(self, job: TrainingJob) -> str:
        """Submit an RLHF preference-tuning job to Vertex AI.

        TODO: Implement using the google-cloud-aiplatform SDK.
          from google.cloud import aiplatform
          aiplatform.init(project=job.config["project"], location=job.config["location"])
          rlhf_job = aiplatform.language_models.TextGenerationModel.get_tuned_model(
              base_model=job.config.get("base_model", "text-bison@002"),
          ).tune_model(
              training_data=job.dataset_path,
              tuning_method="rlhf",
              reward_model_learning_rate=job.config.get("reward_lr", 1e-5),
              reinforcement_learning_rate=job.config.get("rl_lr", 1e-5),
          )
          return rlhf_job.resource_name
        """
        raise NotImplementedError(
            "Vertex Preference start_training requires GCP credentials — not yet wired up."
        )

    def check_status(self, provider_job_id: str) -> TrainingStatus:
        """Poll Vertex AI RLHF pipeline job status.

        TODO: Map PipelineState to TrainingStatus (same mapping as vertex_sft).
        """
        raise NotImplementedError(
            "Vertex Preference check_status requires GCP credentials — not yet wired up."
        )

    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Retrieve the tuned model endpoint and reward model metadata.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).gca_resource
          return {"model_resource": ..., "reward_model_resource": ..., "endpoint": ...}
        """
        raise NotImplementedError(
            "Vertex Preference get_result requires GCP credentials — not yet wired up."
        )

    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a running Vertex AI RLHF pipeline job.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).cancel()
        """
        raise NotImplementedError(
            "Vertex Preference cancel requires GCP credentials — not yet wired up."
        )
