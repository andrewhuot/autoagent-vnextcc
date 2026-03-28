"""Vertex AI Continuous Tuning backend adapter."""

from __future__ import annotations

import json
from typing import Any

from policy_opt.backends.base import TrainingBackend, register_backend
from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


@register_backend("vertex_continuous")
class VertexContinuousBackend(TrainingBackend):
    """Backend for Vertex AI Continuous Tuning.

    Supports all three training modes — verifier, control, and preference —
    by dispatching to the appropriate format validator per mode:

    - verifier / control: expects ``input_text`` + ``output_text`` (SFT layout)
    - preference:         expects ``input_text``, ``candidate_0``,
                          ``candidate_1``, and ``choice`` (RLHF layout)

    Continuous tuning periodically refreshes the model as new data arrives,
    unlike one-shot SFT/RLHF jobs.
    """

    name = "vertex_continuous"
    supported_modes = [TrainingMode.verifier, TrainingMode.control, TrainingMode.preference]

    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate JSONL dataset, dispatching format rules based on ``mode``.

        - verifier / control: requires ``input_text`` (str) and ``output_text`` (str).
        - preference: requires ``input_text`` (str), ``candidate_0`` (str),
          ``candidate_1`` (str), and ``choice`` (int, 0 or 1).
        """
        if mode in (TrainingMode.verifier, TrainingMode.control):
            return self._validate_sft_format(path)
        if mode == TrainingMode.preference:
            return self._validate_preference_format(path)
        return [f"Unsupported mode for {self.name}: {mode}"]

    def _validate_sft_format(self, path: str) -> list[str]:
        """Validate SFT-style JSONL: requires input_text and output_text."""
        errors: list[str] = []
        required = {"input_text", "output_text"}
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
                    for field in required:
                        if field not in record:
                            errors.append(f"Line {lineno}: missing required field '{field}'")
                        elif not isinstance(record[field], str):
                            errors.append(f"Line {lineno}: '{field}' must be a string")
                        elif not record[field].strip():
                            errors.append(f"Line {lineno}: '{field}' must not be empty")
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def _validate_preference_format(self, path: str) -> list[str]:
        """Validate preference-style JSONL: requires input_text, candidates, and choice."""
        errors: list[str] = []
        text_fields = ("input_text", "candidate_0", "candidate_1")
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
                    for field in (*text_fields, "choice"):
                        if field not in record:
                            errors.append(f"Line {lineno}: missing required field '{field}'")
                    for field in text_fields:
                        if field in record:
                            if not isinstance(record[field], str):
                                errors.append(f"Line {lineno}: '{field}' must be a string")
                            elif not record[field].strip():
                                errors.append(f"Line {lineno}: '{field}' must not be empty")
                    if "choice" in record and record["choice"] not in (0, 1):
                        errors.append(
                            f"Line {lineno}: 'choice' must be 0 or 1, got {record['choice']!r}"
                        )
        except FileNotFoundError:
            errors.append(f"Dataset file not found: {path}")
        return errors

    def start_training(self, job: TrainingJob) -> str:
        """Submit a continuous tuning job to Vertex AI.

        TODO: Implement using the google-cloud-aiplatform SDK.
          Continuous tuning wraps a periodic pipeline trigger that re-runs
          SFT or RLHF each time new data is appended to the dataset path.
          from google.cloud import aiplatform
          aiplatform.init(project=job.config["project"], location=job.config["location"])
          pipeline = aiplatform.PipelineJob(
              display_name=f"continuous-tune-{job.job_id}",
              template_path=job.config["pipeline_template"],
              parameter_values={
                  "dataset_uri": job.dataset_path,
                  "tuning_mode": job.mode.value,
                  **job.config.get("pipeline_params", {}),
              },
          )
          pipeline.submit()
          return pipeline.resource_name
        """
        raise NotImplementedError(
            "Vertex Continuous start_training requires GCP credentials — not yet wired up."
        )

    def check_status(self, provider_job_id: str) -> TrainingStatus:
        """Poll Vertex AI pipeline job status.

        TODO: Map PipelineState to TrainingStatus (same mapping as vertex_sft).
        """
        raise NotImplementedError(
            "Vertex Continuous check_status requires GCP credentials — not yet wired up."
        )

    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Retrieve the tuned model endpoint and pipeline run metadata.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).gca_resource
          return {"model_resource": ..., "endpoint": ..., "run_metadata": ...}
        """
        raise NotImplementedError(
            "Vertex Continuous get_result requires GCP credentials — not yet wired up."
        )

    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a running Vertex AI continuous tuning pipeline job.

        TODO: aiplatform.PipelineJob(resource_name=provider_job_id).cancel()
        """
        raise NotImplementedError(
            "Vertex Continuous cancel requires GCP credentials — not yet wired up."
        )
