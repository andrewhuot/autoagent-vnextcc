"""Import ADK agents into AgentLab format.

Layer: Layer 1 (Advanced). May import from Layer 0 / stdlib / PyPI only.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .errors import AdkImportError
from .mapper import AdkMapper
from .parser import parse_agent_directory
from .portability import build_adk_portability_report
from .types import ImportResult


class AdkImporter:
    """Import a ADK agent into AgentLab config format."""

    def __init__(self, parser: None = None, mapper: AdkMapper | None = None):
        """Initialize importer.

        Args:
            parser: Reserved for future use (ADK uses module-level parse function)
            mapper: AdkMapper instance (default: creates new one)
        """
        self._mapper = mapper or AdkMapper()

    def import_agent(
        self,
        agent_path: str,
        output_dir: str = ".",
        save_snapshot: bool = True,
    ) -> ImportResult:
        """Full import pipeline:

        1. Parse agent directory with AdkParser
        2. Map to AgentLab config with AdkMapper
        3. Save config YAML
        4. Save snapshot (copy of original Python source files)
        5. Return ImportResult

        Args:
            agent_path: Path to ADK agent directory
            output_dir: Directory where output files will be written
            save_snapshot: Whether to save original source files

        Returns:
            ImportResult with paths to all written files and a summary

        Raises:
            AdkImportError: On any failure during the import pipeline
        """
        try:
            # 1. Parse agent directory
            agent_path_obj = Path(agent_path).resolve()
            tree = parse_agent_directory(agent_path_obj)

            # 2. Map to AgentLab config
            config = self._mapper.to_agentlab(tree)

            # 3. Prepare output directory
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)

            agent_name = tree.agent.name or "adk_agent"

            # 4a. Write config YAML — strip _adk_metadata before writing
            config_path = str(out / f"{agent_name}_config.yaml")
            adk_metadata = config.pop("_adk_metadata", None)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

            # 4b. Save snapshot (copy entire agent directory)
            snapshot_path = str(out / f"{agent_name}_snapshot")
            if save_snapshot:
                snapshot_dir = Path(snapshot_path)
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
                shutil.copytree(agent_path_obj, snapshot_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

            # Determine which surfaces were mapped
            surfaces: list[str] = []
            if config.get("prompts"):
                surfaces.append("prompts")
            if config.get("tools"):
                surfaces.append("tools")
            if config.get("routing"):
                surfaces.append("routing")
            if config.get("generation"):
                surfaces.append("generation")
            if config.get("model"):
                surfaces.append("model")

            portability_report = build_adk_portability_report(tree)

            return ImportResult(
                config_path=config_path,
                snapshot_path=snapshot_path,
                agent_name=agent_name,
                surfaces_mapped=surfaces,
                tools_imported=len(tree.tools),
                portability_report=portability_report,
            )
        except AdkImportError:
            raise
        except Exception as exc:
            raise AdkImportError(f"Import failed: {exc}") from exc
