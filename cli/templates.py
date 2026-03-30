"""Workspace starter template registry and application helpers."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cli.workspace import AutoAgentWorkspace


STARTER_TEMPLATE_NAMES: tuple[str, ...] = (
    "customer-support",
    "it-helpdesk",
    "sales-qualification",
    "healthcare-intake",
)
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "docs" / "templates"


@dataclass(frozen=True)
class WorkspaceTemplate:
    """Structured starter pack loaded from a YAML template file."""

    name: str
    description: str
    starter_config: dict[str, Any]
    eval_cases: dict[str, dict[str, Any]]
    scorers: dict[str, dict[str, Any]]
    suggested_skills: list[str]


def _template_hash(config: dict[str, Any]) -> str:
    """Return a short stable hash for template-backed config manifests."""
    canonical = yaml.safe_dump(config, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


def _template_path(name: str) -> Path:
    """Resolve the on-disk YAML path for a starter template."""
    return TEMPLATE_DIR / f"{name}.yaml"


def list_templates() -> list[WorkspaceTemplate]:
    """Return all bundled starter templates."""
    templates: list[WorkspaceTemplate] = []
    for name in STARTER_TEMPLATE_NAMES:
        templates.append(load_template(name))
    return templates


def load_template(name: str) -> WorkspaceTemplate:
    """Load one starter template by name."""
    template_path = _template_path(name)
    if not template_path.exists():
        raise FileNotFoundError(f"Unknown starter template: {name}")

    payload = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Template {name} must contain a top-level mapping.")

    starter_config = payload.get("starter_config") or {}
    eval_cases = payload.get("eval_cases") or {}
    scorers = payload.get("scorers") or {}
    suggested_skills = payload.get("suggested_skills") or []

    if not isinstance(starter_config, dict):
        raise ValueError(f"Template {name} has an invalid starter_config payload.")
    if not isinstance(eval_cases, dict):
        raise ValueError(f"Template {name} has an invalid eval_cases payload.")
    if not isinstance(scorers, dict):
        raise ValueError(f"Template {name} has an invalid scorers payload.")

    return WorkspaceTemplate(
        name=str(payload.get("name") or name),
        description=str(payload.get("description") or ""),
        starter_config=starter_config,
        eval_cases=eval_cases,
        scorers=scorers,
        suggested_skills=[str(skill) for skill in suggested_skills],
    )


def apply_template_to_workspace(
    workspace: AutoAgentWorkspace,
    template_name: str,
) -> dict[str, Any]:
    """Write the starter config, eval cases, and scorer specs for a template."""
    template = load_template(template_name)
    workspace.ensure_structure()

    config_path = workspace.configs_dir / "v001.yaml"
    base_config_path = workspace.configs_dir / "v001_base.yaml"
    config_text = yaml.safe_dump(template.starter_config, sort_keys=False)
    config_path.write_text(config_text, encoding="utf-8")
    base_config_path.write_text(config_text, encoding="utf-8")

    manifest_path = workspace.configs_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "versions": [
                    {
                        "version": 1,
                        "config_hash": _template_hash(template.starter_config),
                        "filename": "v001.yaml",
                        "timestamp": time.time(),
                        "scores": {"composite": 0.0},
                        "status": "active",
                    }
                ],
                "active_version": 1,
                "canary_version": None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for existing in workspace.cases_dir.glob("*.yaml"):
        existing.unlink()
    eval_case_count = 0
    for filename, payload in template.eval_cases.items():
        path = workspace.cases_dir / filename
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        if isinstance(payload, dict):
            eval_case_count += len(payload.get("cases") or [])

    for existing in workspace.scorer_specs_dir.glob("*"):
        if existing.is_file():
            existing.unlink()
    for filename, payload in template.scorers.items():
        path = workspace.scorer_specs_dir / filename
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    summary_path = workspace.autoagent_dir / "template.json"
    summary_path.write_text(
        json.dumps(
            {
                "template": template.name,
                "description": template.description,
                "suggested_skills": template.suggested_skills,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    workspace.metadata.template = template.name
    workspace.set_active_config(1, filename="v001.yaml")

    return {
        "template": template.name,
        "description": template.description,
        "config_path": str(config_path),
        "eval_file_count": len(template.eval_cases),
        "eval_case_count": eval_case_count,
        "scorer_count": len(template.scorers),
        "suggested_skills": list(template.suggested_skills),
    }
