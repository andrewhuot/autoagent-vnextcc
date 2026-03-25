"""Import CX Agent Studio agents into AutoAgent format."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .client import CxClient
from .mapper import CxMapper
from .types import CxAgentRef, ImportResult
from .errors import CxImportError


class CxImporter:
    """Import a CX agent into AutoAgent config + eval suite."""

    def __init__(self, client: CxClient, mapper: CxMapper | None = None):
        self._client = client
        self._mapper = mapper or CxMapper()

    def import_agent(
        self,
        ref: CxAgentRef,
        output_dir: str = ".",
        include_test_cases: bool = True,
    ) -> ImportResult:
        """Full import pipeline:

        1. Fetch snapshot from CX API.
        2. Map to AutoAgent config dict.
        3. Extract test cases → eval suite.
        4. Save snapshot for offline use + round-trip export.
        5. Write config YAML + eval JSON files.

        Args:
            ref: Reference identifying the CX agent (project/location/agent triple).
            output_dir: Directory where output files will be written.
            include_test_cases: Whether to extract CX test cases as eval cases.

        Returns:
            ImportResult with paths to all written files and a summary.

        Raises:
            CxImportError: On any failure during the import pipeline.
        """
        try:
            # 1. Fetch snapshot from CX API
            snapshot = self._client.fetch_snapshot(ref)

            # 2. Map to AutoAgent config dict
            config_dict = self._mapper.to_autoagent(snapshot)

            # 3. Extract test cases
            test_cases: list[dict] = []
            if include_test_cases:
                test_cases = self._mapper.extract_test_cases(snapshot)

            # 4. Prepare output directory
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            agent_name = snapshot.agent.display_name.lower().replace(" ", "_")

            # 5a. Write config YAML — strip _cx_metadata before writing
            config_path = str(out / f"{agent_name}_config.yaml")
            cx_metadata = config_dict.pop("_cx_metadata", None)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)

            # 5b. Write eval cases JSON (only when test cases exist)
            eval_path: str | None = None
            if test_cases:
                eval_path = str(out / f"{agent_name}_eval_cases.json")
                with open(eval_path, "w", encoding="utf-8") as f:
                    json.dump(test_cases, f, indent=2)

            # 5c. Write full snapshot JSON for round-trip export
            snapshot_path = str(out / f"{agent_name}_snapshot.json")
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot.model_dump(), f, indent=2)

            # Determine which surfaces were mapped
            surfaces: list[str] = ["prompts"]
            if snapshot.tools:
                surfaces.append("tools")
            if snapshot.flows or snapshot.intents:
                surfaces.append("routing")
            if snapshot.agent.generative_settings:
                surfaces.append("generation_settings")

            return ImportResult(
                config_path=config_path,
                eval_path=eval_path,
                snapshot_path=snapshot_path,
                agent_name=snapshot.agent.display_name,
                surfaces_mapped=surfaces,
                test_cases_imported=len(test_cases),
            )
        except CxImportError:
            raise
        except Exception as exc:
            raise CxImportError(f"Import failed: {exc}") from exc
