"""Helpers for materializing imported runtime specs into AutoAgent workspaces."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from cli.bootstrap import bootstrap_workspace
from cli.workspace import AutoAgentWorkspace, WORKSPACE_DIRNAME

from .base import ConnectWorkspaceResult, ImportedAgentSpec, slugify_label


def create_connected_workspace(
    spec: ImportedAgentSpec,
    *,
    output_dir: str = ".",
    workspace_name: str | None = None,
    runtime_mode: str = "mock",
) -> ConnectWorkspaceResult:
    """Create an AutoAgent workspace seeded from an imported runtime spec."""

    spec.ensure_defaults()
    workspace_root = _resolve_workspace_root(
        Path(output_dir).resolve(),
        workspace_name=workspace_name,
        suggested_name=spec.default_workspace_name(),
    )
    workspace = AutoAgentWorkspace.create(
        workspace_root,
        name=workspace_root.name,
        template="minimal",
        agent_name=spec.agent_name,
        platform=spec.platform,
        demo_seeded=False,
    )
    bootstrap_workspace(
        workspace,
        template="minimal",
        agent_name=spec.agent_name,
        platform=spec.platform,
        with_synthetic_data=False,
        demo=False,
        runtime_mode=runtime_mode,
    )

    config_path = workspace.configs_dir / "v001.yaml"
    base_config_path = workspace.configs_dir / "v001_base.yaml"
    config_path.write_text(yaml.safe_dump(spec.config, sort_keys=False), encoding="utf-8")
    base_config_path.write_text(yaml.safe_dump(spec.config, sort_keys=False), encoding="utf-8")
    workspace.set_active_config(1, filename="v001.yaml")

    spec_path = workspace.autoagent_dir / "adapter_spec.json"
    adapter_config_path = workspace.autoagent_dir / "adapter_config.json"
    spec_path.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")
    adapter_config_path.write_text(json.dumps(spec.adapter_config, indent=2), encoding="utf-8")

    eval_path = workspace.cases_dir / "imported_connect.yaml"
    eval_path.write_text(
        yaml.safe_dump({"cases": spec.starter_evals}, sort_keys=False),
        encoding="utf-8",
    )

    traces_path: Path | None = None
    if spec.traces:
        traces_path = workspace.autoagent_dir / "imported_traces.jsonl"
        traces_path.write_text(
            "\n".join(json.dumps(trace) for trace in spec.traces) + "\n",
            encoding="utf-8",
        )

    return ConnectWorkspaceResult(
        adapter=spec.adapter,
        agent_name=spec.agent_name,
        workspace_path=str(workspace.root),
        config_path=str(config_path),
        eval_path=str(eval_path),
        adapter_config_path=str(adapter_config_path),
        spec_path=str(spec_path),
        traces_path=str(traces_path) if traces_path is not None else None,
        tool_count=len(spec.tools),
        guardrail_count=len(spec.guardrails),
        trace_count=len(spec.traces),
        eval_case_count=len(spec.starter_evals),
    )


def _resolve_workspace_root(
    output_dir: Path,
    *,
    workspace_name: str | None,
    suggested_name: str,
) -> Path:
    """Choose a workspace root without clobbering unrelated directories."""

    output_dir.mkdir(parents=True, exist_ok=True)

    if (output_dir / WORKSPACE_DIRNAME).exists():
        return output_dir

    if workspace_name:
        return output_dir / slugify_label(workspace_name)

    if _directory_is_effectively_empty(output_dir):
        return output_dir

    return output_dir / slugify_label(suggested_name)


def _directory_is_effectively_empty(path: Path) -> bool:
    """Return True when a directory has no user-visible project content."""

    entries = [item for item in path.iterdir() if item.name not in {".DS_Store"}]
    return len(entries) == 0
