"""Import Dialogflow CX agents into AutoAgent workspaces."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.workspace_builder import create_connected_workspace
from .errors import CxImportError
from .mapper import CxMapper
from .types import CxAgentRef, ImportResult


class CxImporter:
    """Import a Dialogflow CX agent into an AutoAgent workspace."""

    def __init__(self, client, mapper: CxMapper | None = None):
        self._client = client
        self._mapper = mapper or CxMapper()

    def import_agent(
        self,
        ref: CxAgentRef,
        output_dir: str = ".",
        include_test_cases: bool = True,
    ) -> ImportResult:
        """Fetch, map, and materialize a CX agent into a workspace."""

        try:
            snapshot = self._client.fetch_snapshot(ref.name)
            workspace_spec = self._mapper.cx_to_workspace(snapshot)

            if not include_test_cases:
                workspace_spec.starter_evals = []

            workspace_result = create_connected_workspace(
                workspace_spec,
                output_dir=output_dir,
                workspace_name=workspace_spec.default_workspace_name(),
                runtime_mode="mock",
            )

            workspace_root = Path(workspace_result.workspace_path)
            cx_dir = workspace_root / ".autoagent" / "cx"
            cx_dir.mkdir(parents=True, exist_ok=True)

            snapshot_path = cx_dir / "snapshot.json"
            workspace_json_path = cx_dir / "workspace.json"
            manifest_path = cx_dir / "manifest.json"

            snapshot_path.write_text(
                json.dumps(snapshot.model_dump(), indent=2),
                encoding="utf-8",
            )
            workspace_json_path.write_text(
                json.dumps(workspace_spec.config, indent=2),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "agent_ref": ref.model_dump(),
                        "agent_name": snapshot.agent.name,
                        "workspace_path": workspace_result.workspace_path,
                        "config_path": workspace_result.config_path,
                        "snapshot_path": str(snapshot_path),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            eval_path = workspace_result.eval_path
            if not include_test_cases:
                eval_file = Path(eval_path)
                if eval_file.exists():
                    eval_file.unlink()
                eval_path = None

            return ImportResult(
                config_path=workspace_result.config_path,
                eval_path=eval_path,
                snapshot_path=str(snapshot_path),
                agent_name=snapshot.agent.display_name or snapshot.agent.name.split("/")[-1],
                surfaces_mapped=self._surfaces(snapshot),
                test_cases_imported=len(workspace_spec.starter_evals) if include_test_cases else 0,
                workspace_path=workspace_result.workspace_path,
            )
        except CxImportError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by higher-level tests
            raise CxImportError(f"Import failed: {exc}") from exc

    @staticmethod
    def _surfaces(snapshot) -> list[str]:
        """Return a concise summary of the imported CX surfaces."""

        surfaces: list[str] = []
        if snapshot.playbooks or snapshot.agent.description:
            surfaces.append("instructions")
            surfaces.append("prompts")
        if snapshot.flows:
            surfaces.append("flows")
        if snapshot.intents:
            surfaces.append("intents")
        if snapshot.entity_types:
            surfaces.append("entities")
        if snapshot.webhooks or snapshot.tools:
            surfaces.append("webhooks")
            surfaces.append("tools")
        if snapshot.test_cases:
            surfaces.append("test_cases")
        return list(dict.fromkeys(surfaces))
