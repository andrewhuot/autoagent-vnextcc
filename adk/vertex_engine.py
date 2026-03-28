"""Vertex AI Agent Engine deployment support."""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any

from adk.errors import AdkDeployError


# Vertex AI Agent Engine pricing (as of 2024)
_VCPU_HOUR_USD = 0.0864  # $0.0864 per vCPU-hour


@dataclass
class VertexEngineConfig:
    """Configuration for a Vertex AI Agent Engine deployment.

    Attributes:
        project_id: GCP project ID.
        location: GCP region (default ``us-central1``).
        agent_name: Display name for the agent resource.
        scaling_config: Scaling parameters such as ``min_replicas``,
            ``max_replicas``, and ``vcpu_count``.
        memory_bank_enabled: Whether to attach a Vertex AI Memory Bank to
            the deployed agent.
    """

    project_id: str
    location: str = "us-central1"
    agent_name: str = ""
    scaling_config: dict[str, Any] = field(default_factory=dict)
    memory_bank_enabled: bool = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "project_id": self.project_id,
            "location": self.location,
            "agent_name": self.agent_name,
            "scaling_config": dict(self.scaling_config),
            "memory_bank_enabled": self.memory_bank_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VertexEngineConfig":
        """Deserialise from a plain dictionary."""
        return cls(
            project_id=data.get("project_id", ""),
            location=data.get("location", "us-central1"),
            agent_name=data.get("agent_name", ""),
            scaling_config=dict(data.get("scaling_config", {})),
            memory_bank_enabled=bool(data.get("memory_bank_enabled", False)),
        )


class VertexEngineDeployer:
    """Deploys and manages agents on Vertex AI Agent Engine.

    This deployer wraps the ``gcloud`` CLI (and optionally the
    ``google-cloud-aiplatform`` SDK) to create, inspect, and teardown
    Vertex AI Agent Engine resources.
    """

    def __init__(self) -> None:
        # In-memory registry of managed deployments (agent_id -> info dict).
        # In production this would be backed by Firestore or a similar store.
        self._deployments: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Deployment lifecycle
    # ------------------------------------------------------------------

    def deploy(
        self,
        config: dict,
        engine_config: VertexEngineConfig,
    ) -> dict:
        """Deploy an agent to Vertex AI Agent Engine.

        Args:
            config: AutoAgent configuration dict for the agent to deploy.
            engine_config: :class:`VertexEngineConfig` describing the target
                Vertex AI project, location, and scaling parameters.

        Returns:
            Deployment result dict with ``agent_id``, ``endpoint``,
            ``status``, ``project_id``, ``location``, and ``details`` fields.

        Raises:
            AdkDeployError: If the deployment command fails.
        """
        agent_name = engine_config.agent_name or config.get("name", "autoagent")
        agent_id = str(uuid.uuid4())

        try:
            self._check_gcloud()
            result = self._run_deploy(agent_name, engine_config, config)
        except AdkDeployError:
            raise
        except Exception as exc:
            raise AdkDeployError(f"Vertex Engine deployment failed: {exc}") from exc

        endpoint = result.get(
            "endpoint",
            (
                f"https://{engine_config.location}-aiplatform.googleapis.com"
                f"/v1/projects/{engine_config.project_id}/locations/"
                f"{engine_config.location}/agents/{agent_id}"
            ),
        )

        info = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "endpoint": endpoint,
            "status": "deployed",
            "project_id": engine_config.project_id,
            "location": engine_config.location,
            "scaling_config": engine_config.scaling_config,
            "memory_bank_enabled": engine_config.memory_bank_enabled,
            "details": result,
        }
        self._deployments[agent_id] = info
        return info

    def undeploy(self, agent_id: str) -> dict:
        """Remove a Vertex AI Agent Engine deployment.

        Args:
            agent_id: Identifier returned by :meth:`deploy`.

        Returns:
            Dict with ``agent_id``, ``status``, and ``message`` fields.

        Raises:
            AdkDeployError: If the agent is not found or the API call fails.
        """
        if agent_id not in self._deployments:
            raise AdkDeployError(f"Agent '{agent_id}' not found in managed deployments.")

        info = self._deployments[agent_id]
        try:
            self._check_gcloud()
            self._run_undeploy(info["agent_name"], info)
        except AdkDeployError:
            raise
        except Exception as exc:
            raise AdkDeployError(f"Undeploy failed: {exc}") from exc

        del self._deployments[agent_id]
        return {
            "agent_id": agent_id,
            "status": "undeployed",
            "message": f"Agent '{info['agent_name']}' successfully removed.",
        }

    def get_status(self, agent_id: str) -> dict:
        """Return the current status of a deployed agent.

        Args:
            agent_id: Identifier returned by :meth:`deploy`.

        Returns:
            Status dict with ``agent_id``, ``status``, ``endpoint``,
            ``project_id``, and ``location`` fields.

        Raises:
            AdkDeployError: If the agent is not found.
        """
        if agent_id not in self._deployments:
            raise AdkDeployError(f"Agent '{agent_id}' not found in managed deployments.")

        info = self._deployments[agent_id]
        try:
            self._check_gcloud()
            live_status = self._run_describe(info["agent_name"], info)
            info.update({"live_status": live_status})
        except Exception:  # noqa: BLE001
            # Return cached info if live check fails
            pass

        return {
            "agent_id": agent_id,
            "agent_name": info.get("agent_name", ""),
            "status": info.get("status", "unknown"),
            "endpoint": info.get("endpoint", ""),
            "project_id": info.get("project_id", ""),
            "location": info.get("location", ""),
            "memory_bank_enabled": info.get("memory_bank_enabled", False),
        }

    def list_deployments(self) -> list[dict]:
        """List all deployments managed by this instance.

        Returns:
            List of status dicts (same shape as :meth:`get_status` output).
        """
        return [
            {
                "agent_id": agent_id,
                "agent_name": info.get("agent_name", ""),
                "status": info.get("status", "unknown"),
                "endpoint": info.get("endpoint", ""),
                "project_id": info.get("project_id", ""),
                "location": info.get("location", ""),
                "memory_bank_enabled": info.get("memory_bank_enabled", False),
            }
            for agent_id, info in self._deployments.items()
        ]

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_cost(self, config: dict) -> dict:
        """Estimate the monthly cost of running an agent configuration.

        Pricing model:
        - Compute: ``$0.0864 / vCPU-hour``
        - Memory: ``$0.012 / GB-hour`` (standard Vertex AI pricing)
        - Memory Bank (if enabled): ``$0.10 / GB-month`` for storage

        Args:
            config: Agent configuration dict. Recognised keys:
                - ``vcpu_count`` (int, default 1)
                - ``memory_gb`` (float, default 2.0)
                - ``replicas`` (int, default 1)
                - ``hours_per_month`` (float, default 730)
                - ``memory_bank_gb`` (float, default 0.0)
                - ``memory_bank_enabled`` (bool, default False)

        Returns:
            Dict with ``vcpu_cost_usd``, ``memory_cost_usd``,
            ``memory_bank_cost_usd``, ``total_usd``, and ``assumptions`` fields.
        """
        vcpu_count = float(config.get("vcpu_count", 1))
        memory_gb = float(config.get("memory_gb", 2.0))
        replicas = int(config.get("replicas", 1))
        hours_per_month = float(config.get("hours_per_month", 730))
        memory_bank_enabled = bool(config.get("memory_bank_enabled", False))
        memory_bank_gb = float(config.get("memory_bank_gb", 1.0)) if memory_bank_enabled else 0.0

        vcpu_cost = _VCPU_HOUR_USD * vcpu_count * replicas * hours_per_month
        memory_cost = 0.012 * memory_gb * replicas * hours_per_month
        memory_bank_cost = 0.10 * memory_bank_gb if memory_bank_enabled else 0.0

        total = vcpu_cost + memory_cost + memory_bank_cost

        return {
            "vcpu_cost_usd": round(vcpu_cost, 4),
            "memory_cost_usd": round(memory_cost, 4),
            "memory_bank_cost_usd": round(memory_bank_cost, 4),
            "total_usd": round(total, 4),
            "assumptions": {
                "vcpu_count": vcpu_count,
                "memory_gb": memory_gb,
                "replicas": replicas,
                "hours_per_month": hours_per_month,
                "vcpu_hour_rate_usd": _VCPU_HOUR_USD,
                "memory_gb_hour_rate_usd": 0.012,
                "memory_bank_enabled": memory_bank_enabled,
                "memory_bank_gb": memory_bank_gb,
            },
        }

    # ------------------------------------------------------------------
    # gcloud wrappers (private)
    # ------------------------------------------------------------------

    def _check_gcloud(self) -> None:
        """Verify that the gcloud CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ["gcloud", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise AdkDeployError("gcloud CLI not configured. Run 'gcloud auth login'.")
        except FileNotFoundError:
            raise AdkDeployError(
                "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
            )
        except subprocess.TimeoutExpired:
            raise AdkDeployError("gcloud check timed out")

    def _run_deploy(
        self,
        agent_name: str,
        engine_config: VertexEngineConfig,
        agent_config: dict,
    ) -> dict:
        """Execute the gcloud command to create the agent resource."""
        scaling = engine_config.scaling_config
        min_replicas = scaling.get("min_replicas", 1)
        max_replicas = scaling.get("max_replicas", 3)

        cmd = [
            "gcloud", "alpha", "ai", "agents", "create",
            agent_name,
            f"--project={engine_config.project_id}",
            f"--region={engine_config.location}",
            f"--min-replicas={min_replicas}",
            f"--max-replicas={max_replicas}",
            "--format=json",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise AdkDeployError(f"gcloud agent create failed: {result.stderr}")
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except subprocess.TimeoutExpired:
            raise AdkDeployError("Vertex Engine deployment timed out")
        except json.JSONDecodeError:
            return {}

    def _run_undeploy(self, agent_name: str, info: dict) -> dict:
        """Execute the gcloud command to delete the agent resource."""
        cmd = [
            "gcloud", "alpha", "ai", "agents", "delete",
            agent_name,
            f"--project={info['project_id']}",
            f"--region={info['location']}",
            "--quiet",
            "--format=json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise AdkDeployError(f"gcloud agent delete failed: {result.stderr}")
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except subprocess.TimeoutExpired:
            raise AdkDeployError("Vertex Engine undeploy timed out")
        except json.JSONDecodeError:
            return {}

    def _run_describe(self, agent_name: str, info: dict) -> dict:
        """Execute the gcloud command to describe the agent resource."""
        cmd = [
            "gcloud", "alpha", "ai", "agents", "describe",
            agent_name,
            f"--project={info['project_id']}",
            f"--region={info['location']}",
            "--format=json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return {}
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return {}
