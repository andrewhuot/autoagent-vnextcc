"""Agent Garden export support for sharing agents via the Vertex AI Agent Garden."""

from __future__ import annotations

import re
from typing import Any


# Required fields that every Agent Garden entry must have
_REQUIRED_FIELDS = ("name", "description", "version")

# Allowed capability categories in Agent Garden
_VALID_CAPABILITY_CATEGORIES = {
    "conversational",
    "task_automation",
    "code_generation",
    "data_analysis",
    "retrieval",
    "tool_use",
    "multi_agent",
    "customer_service",
    "content_generation",
    "reasoning",
}

# Semver pattern (relaxed: major.minor.patch, patch optional)
_SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


class AgentGardenExporter:
    """Exports AutoAgent configurations to the Vertex AI Agent Garden format.

    The Agent Garden is a registry of reusable, shareable agents hosted on
    Vertex AI. This exporter converts an AutoAgent config dict into the
    schema expected by the Agent Garden API, validates it, and returns the
    formatted payload.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, agent_config: dict, metadata: dict) -> dict:
        """Convert an agent configuration to Agent Garden format.

        Args:
            agent_config: AutoAgent configuration dict.  Recognised keys
                include ``name``, ``model``, ``instruction``, ``tools``,
                ``sub_agents``, and ``generate_config``.
            metadata: Extra metadata to embed in the Agent Garden entry.
                Recognised keys include ``description``, ``version``,
                ``author``, ``tags``, ``category``, ``license``,
                ``documentation_url``, and ``source_url``.

        Returns:
            Agent Garden-compatible payload dict with the following top-level
            keys: ``name``, ``display_name``, ``description``, ``version``,
            ``author``, ``tags``, ``category``, ``capabilities``,
            ``agent_config``, ``metadata``, and ``garden_schema_version``.
        """
        name = agent_config.get("name") or metadata.get("name", "")
        display_name = metadata.get("display_name") or _to_display_name(name)
        description = metadata.get("description") or agent_config.get("description", "")
        version = metadata.get("version", "1.0.0")
        author = metadata.get("author", "")
        tags = list(metadata.get("tags", []))
        category = metadata.get("category", "")
        license_id = metadata.get("license", "Apache-2.0")
        documentation_url = metadata.get("documentation_url", "")
        source_url = metadata.get("source_url", "")

        capabilities = self._extract_capabilities(agent_config, metadata)

        # Sanitise the agent config for public sharing (strip secrets)
        public_config = self._sanitise_config(agent_config)

        return {
            "name": _to_resource_name(name),
            "display_name": display_name,
            "description": description,
            "version": version,
            "author": author,
            "tags": tags,
            "category": category,
            "capabilities": capabilities,
            "agent_config": public_config,
            "metadata": {
                "license": license_id,
                "documentation_url": documentation_url,
                "source_url": source_url,
                **{k: v for k, v in metadata.items() if k not in {
                    "description", "version", "author", "tags", "category",
                    "license", "documentation_url", "source_url", "display_name",
                    "name",
                }},
            },
            "garden_schema_version": "1.0",
        }

    def validate_for_garden(self, config: dict) -> list[str]:
        """Validate a garden-format config and return a list of error strings.

        An empty list means the config is valid and ready for submission.

        Args:
            config: A dict previously returned by :meth:`export` or
                assembled manually.

        Returns:
            List of human-readable error strings.  Empty if the config is
            valid.
        """
        errors: list[str] = []

        # Required top-level fields
        for field in _REQUIRED_FIELDS:
            if not config.get(field):
                errors.append(f"Missing required field: '{field}'.")

        # Name must be a valid resource name (lowercase, hyphens/underscores)
        name = config.get("name", "")
        if name and not re.match(r"^[a-z][a-z0-9_-]{0,62}[a-z0-9]$", name):
            errors.append(
                f"'name' must be a lowercase resource name (letters, digits, hyphens, "
                f"underscores; 2–64 chars). Got: '{name}'."
            )

        # Version must look like semver
        version = config.get("version", "")
        if version and not _SEMVER_RE.match(version):
            errors.append(
                f"'version' must follow semver (e.g. '1.0.0'). Got: '{version}'."
            )

        # Description should be non-trivially short
        description = config.get("description", "")
        if description and len(description) < 10:
            errors.append("'description' should be at least 10 characters long.")

        # Category should be a known value (warn but do not hard-fail)
        category = config.get("category", "")
        if category and category not in _VALID_CAPABILITY_CATEGORIES:
            errors.append(
                f"Unknown category '{category}'. "
                f"Valid values: {sorted(_VALID_CAPABILITY_CATEGORIES)}."
            )

        # agent_config must be present
        if "agent_config" not in config:
            errors.append("Missing 'agent_config' section.")
        else:
            agent_cfg = config["agent_config"]
            if not isinstance(agent_cfg, dict):
                errors.append("'agent_config' must be a dictionary.")
            elif not agent_cfg.get("name") and not agent_cfg.get("model"):
                errors.append(
                    "'agent_config' should contain at least 'name' or 'model'."
                )

        # Tags should be a list of strings
        tags = config.get("tags", [])
        if not isinstance(tags, list):
            errors.append("'tags' must be a list.")
        elif any(not isinstance(t, str) for t in tags):
            errors.append("All items in 'tags' must be strings.")

        # Capabilities should be a list of strings
        capabilities = config.get("capabilities", [])
        if not isinstance(capabilities, list):
            errors.append("'capabilities' must be a list.")

        # garden_schema_version must be present
        if not config.get("garden_schema_version"):
            errors.append("Missing 'garden_schema_version'.")

        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_capabilities(
        self, agent_config: dict, metadata: dict
    ) -> list[str]:
        """Infer capability labels from the agent configuration."""
        caps: set[str] = set(metadata.get("capabilities", []))

        tools = agent_config.get("tools", [])
        if tools:
            caps.add("tool_use")

        sub_agents = agent_config.get("sub_agents", [])
        if sub_agents:
            caps.add("multi_agent")

        instruction = (agent_config.get("instruction") or "").lower()
        if any(kw in instruction for kw in ("code", "program", "python", "javascript")):
            caps.add("code_generation")
        if any(kw in instruction for kw in ("search", "retriev", "lookup", "find")):
            caps.add("retrieval")
        if any(kw in instruction for kw in ("customer", "support", "service", "help")):
            caps.add("customer_service")
        if any(kw in instruction for kw in ("analyz", "data", "report", "statistic")):
            caps.add("data_analysis")
        if any(kw in instruction for kw in ("generat", "write", "draft", "content")):
            caps.add("content_generation")
        if any(kw in instruction for kw in ("reason", "think", "plan", "logic")):
            caps.add("reasoning")

        # Default: conversational if nothing else matched
        if not caps:
            caps.add("conversational")

        return sorted(caps)

    def _sanitise_config(self, agent_config: dict) -> dict:
        """Remove secrets and internal-only fields from the config."""
        _SECRET_KEYS = {
            "api_key", "secret", "password", "token", "credential",
            "private_key", "access_key",
        }
        sanitised: dict[str, Any] = {}
        for k, v in agent_config.items():
            if any(secret in k.lower() for secret in _SECRET_KEYS):
                continue
            if isinstance(v, dict):
                sanitised[k] = self._sanitise_config(v)
            else:
                sanitised[k] = v
        return sanitised


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------

def _to_resource_name(name: str) -> str:
    """Convert an arbitrary name to a valid Agent Garden resource name."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-_")
    if not name:
        name = "agent"
    if len(name) < 2:
        name = name + "0"
    return name[:64]


def _to_display_name(name: str) -> str:
    """Convert a resource name to a human-readable display name."""
    return name.replace("-", " ").replace("_", " ").title()
