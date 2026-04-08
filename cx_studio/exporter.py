"""Export AgentLab workspaces back to Dialogflow CX with diff and sync support."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .errors import CxExportError
from .mapper import CxMapper
from .portability import build_cx_export_matrix
from .types import CxAgentRef, CxAgentSnapshot, ChangeSafety, ExportResult

_MISSING = object()


class CxExporter:
    """Export local AgentLab changes to Dialogflow CX resources."""

    def __init__(self, client, mapper: CxMapper | None = None):
        self._client = client
        self._mapper = mapper or CxMapper()

    def export_agent(
        self,
        config: dict[str, Any],
        ref: CxAgentRef,
        snapshot_path: str,
        dry_run: bool = False,
    ) -> ExportResult:
        """Preview or push local workspace changes derived from the base snapshot."""

        try:
            base_snapshot = self._load_snapshot(snapshot_path)
            local_snapshot = self._mapper.to_cx(config, base_snapshot)
            changes = self._compute_changes(base_snapshot, local_snapshot)
            export_matrix = build_cx_export_matrix(base_snapshot)

            if dry_run or not changes:
                return ExportResult(
                    changes=changes,
                    pushed=False,
                    resources_updated=0,
                    conflicts=[],
                    export_matrix=export_matrix,
                )

            resources_updated = self._apply_snapshot_changes(base_snapshot, local_snapshot)
            self._write_snapshot(snapshot_path, local_snapshot)
            return ExportResult(
                changes=changes,
                pushed=True,
                resources_updated=resources_updated,
                conflicts=[],
                export_matrix=export_matrix,
            )
        except CxExportError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by higher-level tests
            raise CxExportError(f"Export failed: {exc}") from exc

    def sync_agent(
        self,
        config: dict[str, Any],
        ref: CxAgentRef,
        snapshot_path: str,
        conflict_strategy: str = "detect",
    ) -> ExportResult:
        """Perform a three-way sync using the imported snapshot as the merge base."""

        try:
            base_snapshot = self._load_snapshot(snapshot_path)
            local_snapshot = self._mapper.to_cx(config, base_snapshot)
            remote_snapshot = self._client.fetch_snapshot(ref.name)
            export_matrix = build_cx_export_matrix(base_snapshot)

            conflicts = self._detect_conflicts(base_snapshot, local_snapshot, remote_snapshot)
            if conflicts and conflict_strategy == "detect":
                return ExportResult(
                    changes=self._compute_changes(base_snapshot, local_snapshot),
                    pushed=False,
                    resources_updated=0,
                    conflicts=conflicts,
                    export_matrix=export_matrix,
                )

            merged_snapshot = self._merge_local_changes(base_snapshot, local_snapshot, remote_snapshot, conflicts)
            changes = self._compute_changes(remote_snapshot, merged_snapshot)
            if not changes:
                return ExportResult(
                    changes=[],
                    pushed=False,
                    resources_updated=0,
                    conflicts=conflicts,
                    export_matrix=export_matrix,
                )

            resources_updated = self._apply_snapshot_changes(remote_snapshot, merged_snapshot)
            self._write_snapshot(snapshot_path, merged_snapshot)
            return ExportResult(
                changes=changes,
                pushed=True,
                resources_updated=resources_updated,
                conflicts=conflicts,
                export_matrix=export_matrix,
            )
        except CxExportError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by higher-level tests
            raise CxExportError(f"Sync failed: {exc}") from exc

    def diff_agent(
        self,
        config: dict[str, Any],
        ref: CxAgentRef,
        snapshot_path: str,
    ) -> ExportResult:
        """Compare the local workspace against the latest remote CX snapshot without pushing."""

        try:
            base_snapshot = self._load_snapshot(snapshot_path)
            local_snapshot = self._mapper.to_cx(config, base_snapshot)
            remote_snapshot = self._client.fetch_snapshot(ref.name)
            conflicts = self._detect_conflicts(base_snapshot, local_snapshot, remote_snapshot)
            merged_snapshot = self._merge_local_changes(base_snapshot, local_snapshot, remote_snapshot, conflicts)
            return ExportResult(
                changes=self._compute_changes(remote_snapshot, merged_snapshot),
                pushed=False,
                resources_updated=0,
                conflicts=conflicts,
                export_matrix=build_cx_export_matrix(base_snapshot),
            )
        except CxExportError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by higher-level tests
            raise CxExportError(f"Diff failed: {exc}") from exc

    def preview_changes(self, config: dict[str, Any], snapshot_path: str) -> list[dict[str, Any]]:
        """Return the local diff without pushing anything."""

        base_snapshot = self._load_snapshot(snapshot_path)
        local_snapshot = self._mapper.to_cx(config, base_snapshot)
        return self._compute_changes(base_snapshot, local_snapshot)

    @staticmethod
    def _load_snapshot(snapshot_path: str) -> CxAgentSnapshot:
        """Load a serialized CX snapshot from disk."""

        payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        return CxAgentSnapshot.model_validate(payload)

    @staticmethod
    def _write_snapshot(snapshot_path: str, snapshot: CxAgentSnapshot) -> None:
        """Persist the latest synchronized snapshot to disk."""

        Path(snapshot_path).write_text(
            json.dumps(snapshot.model_dump(), indent=2),
            encoding="utf-8",
        )

    def _compute_changes(
        self,
        source: CxAgentSnapshot,
        target: CxAgentSnapshot,
    ) -> list[dict[str, Any]]:
        """Compute field-level changes for the CX surfaces we manage.

        Each change is tagged with a ``safety`` classification (safe/lossy/blocked)
        and a ``rationale`` explaining the classification.
        """

        source_fields = self._field_entries(source)
        target_fields = self._field_entries(target)
        changes: list[dict[str, Any]] = []

        for key in sorted(set(source_fields) | set(target_fields)):
            source_entry = source_fields.get(key)
            target_entry = target_fields.get(key)
            source_value = source_entry["value"] if source_entry else _MISSING
            target_value = target_entry["value"] if target_entry else _MISSING
            if source_value == target_value:
                continue

            resource, name, field = key
            display_name = ""
            if target_entry:
                display_name = str(target_entry["display_name"])
            elif source_entry:
                display_name = str(source_entry["display_name"])

            action = "update"
            if source_value is _MISSING:
                action = "add"
            elif target_value is _MISSING:
                action = "delete"

            safety, rationale = self._classify_change_safety(resource, field, action)

            change: dict[str, Any] = {
                "resource": resource,
                "name": display_name or name.split("/")[-1],
                "field": field,
                "action": action,
                "safety": safety.value,
                "rationale": rationale,
            }
            if source_value is not _MISSING:
                change["before"] = source_value
            if target_value is not _MISSING:
                change["after"] = target_value
            changes.append(change)

        return changes

    @staticmethod
    def _classify_change_safety(
        resource: str,
        field: str,
        action: str,
    ) -> tuple[ChangeSafety, str]:
        """Classify a single change as safe, lossy, or blocked.

        Classification is based on which CX surfaces currently support
        round-trip writes via the exporter.
        """

        # Safe: surfaces with full round-trip support
        _SAFE_CHANGES: dict[str, set[str]] = {
            "agent": {"description", "generative_settings"},
            "playbook": {
                "instruction",
                "goal",
                "input_parameter_definitions",
                "output_parameter_definitions",
                "handlers",
            },
            "intent": {"training_phrases", "parameters"},
            "entity_type": {"kind", "auto_expansion_mode", "entities", "excluded_phrases"},
            "webhook": {"generic_web_service", "timeout_seconds", "disabled"},
            "generator": {"prompt_text", "placeholders", "llm_model_settings"},
            "transition_route_group": {"transition_routes"},
        }

        # Lossy: surfaces where writes work but may lose fidelity
        _LOSSY_CHANGES: dict[str, set[str]] = {
            "flow": {"description", "transition_routes", "event_handlers", "transition_route_groups"},
            "page": {"entry_fulfillment", "form", "transition_routes", "event_handlers", "transition_route_groups"},
        }

        safe_fields = _SAFE_CHANGES.get(resource, set())
        if field in safe_fields:
            return ChangeSafety.SAFE, f"{resource}.{field} round-trips faithfully to CX"

        lossy_fields = _LOSSY_CHANGES.get(resource, set())
        if field in lossy_fields:
            return ChangeSafety.LOSSY, f"{resource}.{field} writes back but may lose CX-specific attributes"

        # Everything else is blocked
        return ChangeSafety.BLOCKED, f"{resource}.{field} is read-only and cannot be pushed to CX"

    def _detect_conflicts(
        self,
        base: CxAgentSnapshot,
        local: CxAgentSnapshot,
        remote: CxAgentSnapshot,
    ) -> list[dict[str, Any]]:
        """Detect fields modified both locally and remotely relative to the base."""

        base_fields = self._field_entries(base)
        local_fields = self._field_entries(local)
        remote_fields = self._field_entries(remote)
        conflicts: list[dict[str, Any]] = []

        for key in sorted(set(base_fields) | set(local_fields) | set(remote_fields)):
            base_value = base_fields.get(key, {}).get("value", _MISSING)
            local_value = local_fields.get(key, {}).get("value", _MISSING)
            remote_value = remote_fields.get(key, {}).get("value", _MISSING)

            if local_value == base_value or remote_value == base_value:
                continue
            if local_value == remote_value:
                continue

            resource, name, field = key
            display_name = (
                local_fields.get(key, {}).get("display_name")
                or remote_fields.get(key, {}).get("display_name")
                or name.split("/")[-1]
            )
            conflicts.append(
                {
                    "resource": resource,
                    "name": display_name,
                    "field": field,
                    "base": None if base_value is _MISSING else base_value,
                    "local": None if local_value is _MISSING else local_value,
                    "remote": None if remote_value is _MISSING else remote_value,
                }
            )

        return conflicts

    def _merge_local_changes(
        self,
        base: CxAgentSnapshot,
        local: CxAgentSnapshot,
        remote: CxAgentSnapshot,
        conflicts: list[dict[str, Any]],
    ) -> CxAgentSnapshot:
        """Overlay local-only edits onto the latest remote snapshot."""

        merged = copy.deepcopy(remote)
        conflict_keys = {
            (conflict["resource"], conflict["name"], conflict["field"])
            for conflict in conflicts
        }

        base_fields = self._field_entries(base)
        local_fields = self._field_entries(local)
        for key, local_entry in local_fields.items():
            base_value = base_fields.get(key, {}).get("value", _MISSING)
            local_value = local_entry["value"]
            if local_value == base_value:
                continue

            resource, _resource_name, field = key
            if (resource, local_entry["display_name"], field) in conflict_keys:
                continue
            self._set_field(merged, key, local_value)

        return merged

    def _apply_snapshot_changes(
        self,
        source: CxAgentSnapshot,
        target: CxAgentSnapshot,
    ) -> int:
        """Push the target snapshot delta to the CX API."""

        updated_resources = 0

        if source.agent.description != target.agent.description or source.agent.generative_settings != target.agent.generative_settings:
            update_mask: list[str] = []
            payload: dict[str, Any] = {
                "displayName": target.agent.display_name,
            }
            if source.agent.description != target.agent.description:
                payload["description"] = target.agent.description
                update_mask.append("description")
            if source.agent.generative_settings != target.agent.generative_settings:
                payload["generativeSettings"] = target.agent.generative_settings
                update_mask.append("generative_settings")
            self._client.update_agent(target.agent.name, payload, update_mask=update_mask or None)
            updated_resources += 1

        updated_resources += self._apply_playbook_changes(source, target)
        updated_resources += self._apply_flow_changes(source, target)
        updated_resources += self._apply_page_changes(source, target)
        updated_resources += self._apply_transition_route_group_changes(source, target)
        updated_resources += self._apply_intent_changes(source, target)
        updated_resources += self._apply_entity_type_changes(source, target)
        updated_resources += self._apply_generator_changes(source, target)
        updated_resources += self._apply_webhook_changes(source, target)
        return updated_resources

    def _apply_playbook_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push playbook adds/updates."""

        updated = 0
        source_map = {playbook.name: playbook for playbook in source.playbooks}
        for playbook in target.playbooks:
            original = source_map.get(playbook.name)
            payload = {
                "displayName": playbook.display_name,
                "instruction": playbook.instruction_text,
                "goal": playbook.goal,
                "inputParameterDefinitions": playbook.input_parameter_definitions,
                "outputParameterDefinitions": playbook.output_parameter_definitions,
                "handlers": playbook.handlers,
            }
            if original is None:
                self._client.create_playbook(target.agent.name, payload)
                updated += 1
            elif (
                original.instruction_text != playbook.instruction_text
                or original.goal != playbook.goal
                or original.input_parameter_definitions != playbook.input_parameter_definitions
                or original.output_parameter_definitions != playbook.output_parameter_definitions
                or original.handlers != playbook.handlers
            ):
                self._client.update_playbook(
                    playbook.name,
                    payload,
                    update_mask=[
                        "instruction",
                        "goal",
                        "input_parameter_definitions",
                        "output_parameter_definitions",
                        "handlers",
                    ],
                )
                updated += 1
        return updated

    def _apply_flow_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push flow adds/updates."""

        updated = 0
        source_map = {flow.name: flow for flow in source.flows}
        for flow in target.flows:
            original = source_map.get(flow.name)
            payload = {
                "displayName": flow.display_name,
                "description": flow.description,
                "transitionRoutes": flow.transition_routes,
                "eventHandlers": flow.event_handlers,
                "transitionRouteGroups": flow.transition_route_groups,
            }
            if original is None:
                self._client.create_flow(target.agent.name, payload)
                updated += 1
            elif (
                original.description != flow.description
                or original.transition_routes != flow.transition_routes
                or original.event_handlers != flow.event_handlers
                or original.transition_route_groups != flow.transition_route_groups
            ):
                self._client.update_flow(
                    flow.name,
                    payload,
                    update_mask=[
                        "description",
                        "transition_routes",
                        "event_handlers",
                        "transition_route_groups",
                    ],
                )
                updated += 1
        return updated

    def _apply_page_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push page updates for existing flows."""

        updated = 0
        source_pages = {
            page.name: page
            for flow in source.flows
            for page in flow.pages
        }

        for flow in target.flows:
            for page in flow.pages:
                original = source_pages.get(page.name)
                if original is None:
                    continue
                if (
                    original.entry_fulfillment == page.entry_fulfillment
                    and original.form == page.form
                    and original.transition_routes == page.transition_routes
                    and original.event_handlers == page.event_handlers
                    and original.transition_route_groups == page.transition_route_groups
                ):
                    continue
                self._client.update_page(
                    page.name,
                    {
                        "displayName": page.display_name,
                        "entryFulfillment": page.entry_fulfillment,
                        "form": page.form,
                        "transitionRoutes": page.transition_routes,
                        "eventHandlers": page.event_handlers,
                        "transitionRouteGroups": page.transition_route_groups,
                    },
                    update_mask=[
                        "entry_fulfillment",
                        "form",
                        "transition_routes",
                        "event_handlers",
                        "transition_route_groups",
                    ],
                )
                updated += 1
        return updated

    def _apply_transition_route_group_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push transition route group adds/updates."""

        updated = 0
        source_map = {
            route_group.name: route_group
            for route_group in source.transition_route_groups
        }
        for route_group in target.transition_route_groups:
            payload = {
                "displayName": route_group.display_name,
                "transitionRoutes": route_group.transition_routes,
            }
            original = source_map.get(route_group.name)
            if original is None:
                self._client.create_transition_route_group(target.agent.name, payload)
                updated += 1
            elif original.transition_routes != route_group.transition_routes:
                self._client.update_transition_route_group(
                    route_group.name,
                    payload,
                    update_mask=["transition_routes"],
                )
                updated += 1
        return updated

    def _apply_intent_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push intent adds/updates."""

        updated = 0
        source_map = {intent.name: intent for intent in source.intents}
        for intent in target.intents:
            original = source_map.get(intent.name)
            payload = {
                "displayName": intent.display_name,
                "trainingPhrases": intent.training_phrases,
                "parameters": intent.parameters,
            }
            if original is None:
                self._client.create_intent(target.agent.name, payload)
                updated += 1
            elif (
                original.training_phrases != intent.training_phrases
                or original.parameters != intent.parameters
            ):
                self._client.update_intent(
                    intent.name,
                    payload,
                    update_mask=["training_phrases", "parameters"],
                )
                updated += 1
        return updated

    def _apply_entity_type_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push entity type adds/updates."""

        updated = 0
        source_map = {entity_type.name: entity_type for entity_type in source.entity_types}
        for entity_type in target.entity_types:
            original = source_map.get(entity_type.name)
            if original is None:
                self._client.create_entity_type(
                    target.agent.name,
                    {
                        "displayName": entity_type.display_name,
                        "kind": entity_type.kind,
                        "autoExpansionMode": entity_type.auto_expansion_mode,
                        "entities": entity_type.entities,
                        "excludedPhrases": entity_type.excluded_phrases,
                    },
                )
                updated += 1
            elif (
                original.entities != entity_type.entities
                or original.excluded_phrases != entity_type.excluded_phrases
                or original.kind != entity_type.kind
                or original.auto_expansion_mode != entity_type.auto_expansion_mode
            ):
                self._client.update_entity_type(
                    entity_type.name,
                    {
                        "displayName": entity_type.display_name,
                        "kind": entity_type.kind,
                        "autoExpansionMode": entity_type.auto_expansion_mode,
                        "entities": entity_type.entities,
                        "excludedPhrases": entity_type.excluded_phrases,
                    },
                    update_mask=["kind", "auto_expansion_mode", "entities", "excluded_phrases"],
                )
                updated += 1
        return updated

    def _apply_generator_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push generator adds/updates."""

        updated = 0
        source_map = {generator.name: generator for generator in source.generators}
        for generator in target.generators:
            payload = {
                "displayName": generator.display_name,
                "promptText": generator.prompt_text,
                "placeholders": generator.placeholders,
                "llmModelSettings": generator.llm_model_settings,
            }
            original = source_map.get(generator.name)
            if original is None:
                self._client.create_generator(target.agent.name, payload)
                updated += 1
            elif (
                original.prompt_text != generator.prompt_text
                or original.placeholders != generator.placeholders
                or original.llm_model_settings != generator.llm_model_settings
            ):
                self._client.update_generator(
                    generator.name,
                    payload,
                    update_mask=["prompt_text", "placeholders", "llm_model_settings"],
                )
                updated += 1
        return updated

    def _apply_webhook_changes(self, source: CxAgentSnapshot, target: CxAgentSnapshot) -> int:
        """Push webhook adds/updates."""

        updated = 0
        source_map = {webhook.name: webhook for webhook in source.webhooks}
        for webhook in target.webhooks:
            original = source_map.get(webhook.name)
            payload = {
                "displayName": webhook.display_name,
                "genericWebService": webhook.generic_web_service,
                "timeout": f"{webhook.timeout_seconds}s",
                "disabled": webhook.disabled,
            }
            if original is None:
                self._client.create_webhook(target.agent.name, payload)
                updated += 1
            elif (
                original.generic_web_service != webhook.generic_web_service
                or original.timeout_seconds != webhook.timeout_seconds
                or original.disabled != webhook.disabled
            ):
                self._client.update_webhook(
                    webhook.name,
                    payload,
                    update_mask=["generic_web_service", "timeout", "disabled"],
                )
                updated += 1
        return updated

    @staticmethod
    def _field_entries(snapshot: CxAgentSnapshot) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Flatten a snapshot into comparable managed fields."""

        fields: dict[tuple[str, str, str], dict[str, Any]] = {
            ("agent", snapshot.agent.name, "description"): {
                "value": snapshot.agent.description,
                "display_name": snapshot.agent.display_name or snapshot.agent.name.split("/")[-1],
            },
            ("agent", snapshot.agent.name, "generative_settings"): {
                "value": snapshot.agent.generative_settings,
                "display_name": snapshot.agent.display_name or snapshot.agent.name.split("/")[-1],
            },
        }

        for playbook in snapshot.playbooks:
            fields[("playbook", playbook.name, "instruction")] = {
                "value": playbook.instruction_text,
                "display_name": playbook.display_name or playbook.name.split("/")[-1],
            }
            fields[("playbook", playbook.name, "input_parameter_definitions")] = {
                "value": playbook.input_parameter_definitions,
                "display_name": playbook.display_name or playbook.name.split("/")[-1],
            }
            fields[("playbook", playbook.name, "output_parameter_definitions")] = {
                "value": playbook.output_parameter_definitions,
                "display_name": playbook.display_name or playbook.name.split("/")[-1],
            }
            fields[("playbook", playbook.name, "handlers")] = {
                "value": playbook.handlers,
                "display_name": playbook.display_name or playbook.name.split("/")[-1],
            }

        for flow in snapshot.flows:
            fields[("flow", flow.name, "description")] = {
                "value": flow.description,
                "display_name": flow.display_name or flow.name.split("/")[-1],
            }
            fields[("flow", flow.name, "transition_routes")] = {
                "value": flow.transition_routes,
                "display_name": flow.display_name or flow.name.split("/")[-1],
            }
            fields[("flow", flow.name, "event_handlers")] = {
                "value": flow.event_handlers,
                "display_name": flow.display_name or flow.name.split("/")[-1],
            }
            fields[("flow", flow.name, "transition_route_groups")] = {
                "value": flow.transition_route_groups,
                "display_name": flow.display_name or flow.name.split("/")[-1],
            }
            for page in flow.pages:
                fields[("page", page.name, "form")] = {
                    "value": page.form,
                    "display_name": page.display_name or page.name.split("/")[-1],
                }
                fields[("page", page.name, "transition_routes")] = {
                    "value": page.transition_routes,
                    "display_name": page.display_name or page.name.split("/")[-1],
                }
                fields[("page", page.name, "event_handlers")] = {
                    "value": page.event_handlers,
                    "display_name": page.display_name or page.name.split("/")[-1],
                }
                fields[("page", page.name, "transition_route_groups")] = {
                    "value": page.transition_route_groups,
                    "display_name": page.display_name or page.name.split("/")[-1],
                }

        for intent in snapshot.intents:
            fields[("intent", intent.name, "training_phrases")] = {
                "value": intent.training_phrases,
                "display_name": intent.display_name or intent.name.split("/")[-1],
            }
            fields[("intent", intent.name, "parameters")] = {
                "value": intent.parameters,
                "display_name": intent.display_name or intent.name.split("/")[-1],
            }

        for entity_type in snapshot.entity_types:
            fields[("entity_type", entity_type.name, "kind")] = {
                "value": entity_type.kind,
                "display_name": entity_type.display_name or entity_type.name.split("/")[-1],
            }
            fields[("entity_type", entity_type.name, "entities")] = {
                "value": entity_type.entities,
                "display_name": entity_type.display_name or entity_type.name.split("/")[-1],
            }
            fields[("entity_type", entity_type.name, "excluded_phrases")] = {
                "value": entity_type.excluded_phrases,
                "display_name": entity_type.display_name or entity_type.name.split("/")[-1],
            }

        for webhook in snapshot.webhooks:
            fields[("webhook", webhook.name, "generic_web_service")] = {
                "value": webhook.generic_web_service,
                "display_name": webhook.display_name or webhook.name.split("/")[-1],
            }
            fields[("webhook", webhook.name, "timeout_seconds")] = {
                "value": webhook.timeout_seconds,
                "display_name": webhook.display_name or webhook.name.split("/")[-1],
            }
            fields[("webhook", webhook.name, "disabled")] = {
                "value": webhook.disabled,
                "display_name": webhook.display_name or webhook.name.split("/")[-1],
            }

        for route_group in snapshot.transition_route_groups:
            fields[("transition_route_group", route_group.name, "transition_routes")] = {
                "value": route_group.transition_routes,
                "display_name": route_group.display_name or route_group.name.split("/")[-1],
            }

        for generator in snapshot.generators:
            fields[("generator", generator.name, "prompt_text")] = {
                "value": generator.prompt_text,
                "display_name": generator.display_name or generator.name.split("/")[-1],
            }
            fields[("generator", generator.name, "placeholders")] = {
                "value": generator.placeholders,
                "display_name": generator.display_name or generator.name.split("/")[-1],
            }
            fields[("generator", generator.name, "llm_model_settings")] = {
                "value": generator.llm_model_settings,
                "display_name": generator.display_name or generator.name.split("/")[-1],
            }

        return fields

    @staticmethod
    def _set_field(snapshot: CxAgentSnapshot, key: tuple[str, str, str], value: Any) -> None:
        """Set a flattened field on a snapshot object."""

        resource_type, resource_name, field = key
        if resource_type == "agent":
            if field == "description":
                snapshot.agent.description = value
            elif field == "generative_settings":
                snapshot.agent.generative_settings = value
            return

        if resource_type == "playbook":
            for playbook in snapshot.playbooks:
                if playbook.name != resource_name:
                    continue
                if field == "instruction":
                    playbook.instruction = value
                    playbook.instructions = [line for line in str(value).splitlines() if line.strip()]
                elif field == "input_parameter_definitions":
                    playbook.input_parameter_definitions = value
                elif field == "output_parameter_definitions":
                    playbook.output_parameter_definitions = value
                elif field == "handlers":
                    playbook.handlers = value
                return

        if resource_type == "flow":
            for flow in snapshot.flows:
                if flow.name != resource_name:
                    continue
                if field == "description":
                    flow.description = value
                elif field == "transition_routes":
                    flow.transition_routes = value
                elif field == "event_handlers":
                    flow.event_handlers = value
                elif field == "transition_route_groups":
                    flow.transition_route_groups = value
                return

        if resource_type == "page":
            for flow in snapshot.flows:
                for page in flow.pages:
                    if page.name != resource_name:
                        continue
                    if field == "form":
                        page.form = value
                    elif field == "transition_routes":
                        page.transition_routes = value
                    elif field == "event_handlers":
                        page.event_handlers = value
                    elif field == "transition_route_groups":
                        page.transition_route_groups = value
                    return

        if resource_type == "intent":
            for intent in snapshot.intents:
                if intent.name != resource_name:
                    continue
                if field == "training_phrases":
                    intent.training_phrases = value
                elif field == "parameters":
                    intent.parameters = value
                return

        if resource_type == "entity_type":
            for entity_type in snapshot.entity_types:
                if entity_type.name != resource_name:
                    continue
                if field == "kind":
                    entity_type.kind = value
                elif field == "entities":
                    entity_type.entities = value
                elif field == "excluded_phrases":
                    entity_type.excluded_phrases = value
                return

        if resource_type == "webhook":
            for webhook in snapshot.webhooks:
                if webhook.name != resource_name:
                    continue
                if field == "generic_web_service":
                    webhook.generic_web_service = value
                elif field == "timeout_seconds":
                    webhook.timeout_seconds = value
                elif field == "disabled":
                    webhook.disabled = value
                return

        if resource_type == "transition_route_group":
            for route_group in snapshot.transition_route_groups:
                if route_group.name == resource_name and field == "transition_routes":
                    route_group.transition_routes = value
                    return

        if resource_type == "generator":
            for generator in snapshot.generators:
                if generator.name != resource_name:
                    continue
                if field == "prompt_text":
                    generator.prompt_text = value
                elif field == "placeholders":
                    generator.placeholders = value
                elif field == "llm_model_settings":
                    generator.llm_model_settings = value
                return
