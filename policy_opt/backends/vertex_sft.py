"""Vertex AI Supervised Fine-Tuning (SFT) backend adapter."""

from __future__ import annotations

import json
from typing import Any

from policy_opt.backends.base import TrainingBackend, register_backend
from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


@register_backend("vertex_sft")
class VertexSFTBackend(TrainingBackend):
    """Backend for Vertex AI Supervised Fine-Tuning.

    Supports verifier-mode and control-mode training. Each training example
    must supply ``input_text`` (the model prompt) and ``output_text`` (the
    expected completion), which maps to Vertex AI's standard SFT JSONL format.
    """

    name = "vertex_sft"
    supported_modes = [TrainingMode.verifier, TrainingMode.control]

    # Required top-level fields per training example.
    _REQUIRED_FIELDS = {"input_text", "output_text"}

    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate JSONL dataset for Vertex AI SFT format.

        Each line must be valid JSON containing ``input_text`` (str) and
        ``output_text`` (str).  Both fields must be non-empty strings.
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
                        elif not isinstance(record[field], str):
                            errors.append(f"Line {lineno}: '{field}' must be a string")
                        elif not record[field].strip():
                            errors.append(f"Line {lineno}: '{field}' must not be empty")
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def start_training(self, job: TrainingJob) -> str:
        """Submit a supervised fine-tuning job to Vertex AI.

        TODO: Implement using the google-cloud-aiplatform SDK.
          from google.cloud import aiplatform
          aiplatform.init(project=job.config["project"], location=job.config["location"])
          sft_job = aiplatform.language_models.TextGenerationModel.get_tuned_model(
              base_model=job.config.get("base_model", "text-bison@002"),
          ).tune_model(
              training_data=job.dataset_path,
              train_steps=job.config.get("train_steps", 300),
              tuning_job_location=job.config["location"],
              tuned_model_location=job.config["location"],
          )
          return sft_job.resource_name
        """
        raise NotImplementedError(
            "Vertex SFT start_training requires GCP credentials — not yet wired up."
        )

    def check_status(self, provider_job_id: str) -> TrainingStatus:
        """Poll Vertex AI pipeline job status.

        TODO: Map PipelineState to TrainingStatus:
          PIPELINE_STATE_PENDING / QUEUED -> pending
          PIPELINE_STATE_RUNNING          -> running
          PIPELINE_STATE_SUCCEEDED        -> completed
          PIPELINE_STATE_FAILED           -> failed
          PIPELINE_STATE_CANCELLED        -> cancelled
        """
        raise NotImplementedError(
            "Vertex SFT check_status requires GCP credentials — not yet wired up."
        )

    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Retrieve the tuned model endpoint and job metadata.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).gca_resource
          return {"model_resource": ..., "endpoint": ...}
        """
        raise NotImplementedError(
            "Vertex SFT get_result requires GCP credentials — not yet wired up."
        )

    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a running Vertex AI pipeline job.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).cancel()
        """
        raise NotImplementedError(
            "Vertex SFT cancel requires GCP credentials — not yet wired up."
        )
