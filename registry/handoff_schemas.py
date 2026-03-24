"""Versioned CRUD for handoff schemas. Wraps HandoffArtifact."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from registry.store import RegistryStore


class HandoffSchemaRegistry:
    """Versioned CRUD for handoff schemas."""

    TABLE = "handoff_schemas"

    def __init__(self, store: RegistryStore) -> None:
        self.store = store

    def register(
        self,
        name: str,
        from_agent: str,
        to_agent: str,
        required_fields: list[str],
        optional_fields: list[str] | None = None,
        validation_rules: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Register a new handoff schema version. Returns (name, version)."""
        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()

        data: dict[str, Any] = {
            "name": name,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "required_fields": required_fields,
            "optional_fields": optional_fields or [],
            "validation_rules": validation_rules or {},
            "metadata": metadata or {},
        }

        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def get(self, name: str, version: int | None = None) -> dict[str, Any] | None:
        """Get a handoff schema by name and optional version."""
        return self.store._get(self.TABLE, name, version)

    def list(self, include_deprecated: bool = False) -> list[dict[str, Any]]:
        """List all handoff schemas."""
        return self.store._list(self.TABLE, include_deprecated)

    def validate_handoff(
        self,
        schema_name: str,
        artifact: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate a handoff artifact against the schema.

        Returns (is_valid, list_of_errors).
        """
        schema_item = self.store._get(self.TABLE, schema_name)
        if schema_item is None:
            return (False, [f"Schema '{schema_name}' not found"])

        schema_data = schema_item["data"]
        errors: list[str] = []

        for field_name in schema_data.get("required_fields", []):
            if field_name not in artifact or not artifact[field_name]:
                errors.append(f"Missing required field: {field_name}")

        # Apply validation rules if present
        validation_rules = schema_data.get("validation_rules", {})
        for field_name, rule in validation_rules.items():
            if field_name in artifact:
                value = artifact[field_name]
                if isinstance(rule, dict):
                    if "type" in rule:
                        expected_type = rule["type"]
                        type_map = {
                            "str": str, "string": str,
                            "int": int, "integer": int,
                            "float": float, "number": (int, float),
                            "list": list, "array": list,
                            "dict": dict, "object": dict,
                            "bool": bool, "boolean": bool,
                        }
                        expected = type_map.get(expected_type)
                        if expected and not isinstance(value, expected):
                            errors.append(
                                f"Field '{field_name}' expected type {expected_type}, "
                                f"got {type(value).__name__}"
                            )
                    if "min_length" in rule:
                        if hasattr(value, "__len__") and len(value) < rule["min_length"]:
                            errors.append(
                                f"Field '{field_name}' length {len(value)} "
                                f"below minimum {rule['min_length']}"
                            )

        return (len(errors) == 0, errors)
