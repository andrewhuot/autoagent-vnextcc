"""Agent Library routes backed by workspace configs."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from builder.chat_service import BuilderChatService
from builder.workspace_config import persist_generated_config
from shared.build_artifact_store import BuildArtifactStore

router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENT_ID_RE = re.compile(r"^agent-v(?P<version>\d+)$")


class SaveAgentRequest(BaseModel):
    """Save or register an agent in the shared library."""

    source: str = Field("built", pattern="^(built|imported|connected)$")
    build_source: str | None = Field(None, pattern="^(prompt|transcript|builder_chat)$")
    name: str | None = None
    config: dict[str, Any] | None = None
    session_id: str | None = None
    config_path: str | None = None
    prompt_used: str | None = None
    transcript_report_id: str | None = None
    builder_session_id: str | None = None


def _get_build_artifact_store(request: Request) -> BuildArtifactStore:
    store = getattr(request.app.state, "build_artifact_store", None)
    if store is None:
        store = BuildArtifactStore()
        request.app.state.build_artifact_store = store
    return store


def _get_version_manager(request: Request) -> Any:
    version_manager = getattr(request.app.state, "version_manager", None)
    if version_manager is None:
        raise HTTPException(status_code=500, detail="Version manager is not configured")
    if hasattr(version_manager, "_load_manifest"):
        version_manager.manifest = version_manager._load_manifest()
    return version_manager


def _get_builder_chat_service(request: Request) -> BuilderChatService:
    service = getattr(request.app.state, "builder_chat_service", None)
    if service is None:
        service = BuilderChatService(
            studio_service=getattr(request.app.state, "transcript_intelligence_service", None),
            build_artifact_store=_get_build_artifact_store(request),
        )
        request.app.state.builder_chat_service = service
    return service


def _valid_agent_source(value: Any) -> str | None:
    source = str(value or "").strip().lower()
    if source in {"built", "imported", "connected"}:
        return source
    return None


def _agent_id(version: int) -> str:
    return f"agent-v{version:03d}"


def _isoformat(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value:
        return value
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _load_yaml_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"Config file must contain a mapping: {path}")
    return payload


def _artifact_index(request: Request) -> dict[Path, dict[str, Any]]:
    store = getattr(request.app.state, "build_artifact_store", None)
    if store is None:
        return {}

    indexed: dict[Path, dict[str, Any]] = {}
    for artifact in store.list_recent(limit=200):
        starter_path = artifact.get("starter_config_path")
        if not starter_path:
            continue
        indexed[Path(starter_path).resolve()] = artifact
    return indexed


def _extract_agent_name(config: dict[str, Any], path: Path, artifact: dict[str, Any] | None) -> str:
    journey_build = config.get("journey_build")
    journey_build = journey_build if isinstance(journey_build, dict) else {}
    if journey_build.get("agent_name"):
        return str(journey_build["agent_name"])

    metadata = journey_build.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if metadata.get("agent_name"):
        return str(metadata["agent_name"])

    agent_block = config.get("agent")
    agent_block = agent_block if isinstance(agent_block, dict) else {}
    if agent_block.get("name"):
        return str(agent_block["name"])

    if config.get("agent_name"):
        return str(config["agent_name"])
    if config.get("name"):
        return str(config["name"])

    library_meta = config.get("agent_library")
    library_meta = library_meta if isinstance(library_meta, dict) else {}
    if library_meta.get("name"):
        return str(library_meta["name"])

    if artifact is not None:
        metadata = artifact.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("title"):
            return str(metadata["title"])

    return path.stem


def _extract_agent_model(config: dict[str, Any]) -> str:
    journey_build = config.get("journey_build")
    journey_build = journey_build if isinstance(journey_build, dict) else {}
    if journey_build.get("model"):
        return str(journey_build["model"])

    library_meta = config.get("agent_library")
    library_meta = library_meta if isinstance(library_meta, dict) else {}
    if library_meta.get("model"):
        return str(library_meta["model"])

    return str(config.get("model") or "unknown")


def _extract_agent_source(config: dict[str, Any], artifact: dict[str, Any] | None) -> str:
    journey_build = config.get("journey_build")
    if isinstance(journey_build, dict) and journey_build:
        return "built"

    if artifact is not None:
        artifact_source = str(artifact.get("source") or "").strip().lower()
        if artifact_source in {"prompt", "transcript", "builder_chat", "cli"}:
            return "built"

    library_meta = config.get("agent_library")
    library_meta = library_meta if isinstance(library_meta, dict) else {}
    explicit = _valid_agent_source(library_meta.get("source"))
    if explicit is not None:
        return explicit

    return "connected"


def _list_entries(request: Request) -> list[dict[str, Any]]:
    version_manager = _get_version_manager(request)
    return list(version_manager.manifest.get("versions", []))


def _entry_to_agent(
    request: Request,
    entry: dict[str, Any],
    *,
    include_config: bool = False,
) -> dict[str, Any]:
    version_manager = _get_version_manager(request)

    config_path = version_manager.configs_dir / str(entry["filename"])
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Config file not found: {entry['filename']}")

    config = _load_yaml_config(config_path)
    artifact = _artifact_index(request).get(config_path.resolve())

    agent = {
        "id": _agent_id(int(entry["version"])),
        "config_version": int(entry["version"]),
        "name": _extract_agent_name(config, config_path, artifact),
        "model": _extract_agent_model(config),
        "created_at": _isoformat(entry.get("timestamp")),
        "source": _extract_agent_source(config, artifact),
        "config_path": str(config_path),
        "status": str(entry.get("status") or "saved"),
    }
    if include_config:
        agent["config"] = config
    return agent


def _find_entry(agent_id: str, request: Request) -> dict[str, Any]:
    match = _AGENT_ID_RE.match(agent_id)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    version = int(match.group("version"))
    for entry in _list_entries(request):
        if int(entry["version"]) == version:
            return entry
    raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")


def _save_existing_config(
    request: Request,
    *,
    config: dict[str, Any],
    source: str,
    name: str | None,
) -> dict[str, Any]:
    version_manager = _get_version_manager(request)

    saved_config = copy.deepcopy(config)
    saved_config["agent_library"] = {
        **(
            saved_config.get("agent_library")
            if isinstance(saved_config.get("agent_library"), dict)
            else {}
        ),
        "source": source,
        "name": name or _extract_agent_name(saved_config, version_manager.configs_dir / "agent.yaml", None),
        "model": _extract_agent_model(saved_config),
    }

    saved_version = version_manager.save_version(saved_config, scores={"composite": 0.0}, status="candidate")
    return {
        "agent": _entry_to_agent(
            request,
            {
                "version": saved_version.version,
                "filename": saved_version.filename,
                "timestamp": saved_version.timestamp,
                "status": saved_version.status,
            },
            include_config=True,
        ),
        "save_result": None,
    }


@router.get("")
async def list_agents(request: Request) -> dict[str, Any]:
    """List saved agents from the current workspace config library."""
    agents = [_entry_to_agent(request, entry) for entry in _list_entries(request)]
    agents.sort(key=lambda agent: agent["created_at"], reverse=True)
    return {"agents": agents, "count": len(agents)}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, request: Request) -> dict[str, Any]:
    """Return one agent record plus its parsed config."""
    entry = _find_entry(agent_id, request)
    return _entry_to_agent(request, entry, include_config=True)


@router.post("", status_code=201)
async def save_agent(body: SaveAgentRequest, request: Request) -> dict[str, Any]:
    """Persist a new agent into the shared library."""
    request_count = sum(
        item is not None
        for item in (body.config, body.session_id, body.config_path)
    )
    if request_count != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of config, session_id, or config_path",
        )

    if body.session_id is not None:
        service = _get_builder_chat_service(request)
        saved_payload = service.save_session(body.session_id)
        if saved_payload is None:
            raise HTTPException(status_code=404, detail="Builder session not found")
        return {
            "agent": _entry_to_agent(request, _find_entry(_agent_id(saved_payload["config_version"]), request), include_config=True),
            "save_result": saved_payload,
        }

    if body.config is not None:
        if body.source == "built":
            saved = persist_generated_config(
                body.config,
                artifact_store=_get_build_artifact_store(request),
                source=body.build_source or "prompt",
                source_prompt=body.prompt_used,
                transcript_report_id=body.transcript_report_id,
                builder_session_id=body.builder_session_id,
            )
            return {
                "agent": _entry_to_agent(
                    request,
                    _find_entry(_agent_id(saved.config_version), request),
                    include_config=True,
                ),
                "save_result": saved.to_dict(),
            }
        return _save_existing_config(request, config=body.config, source=body.source, name=body.name)

    config_path = Path(body.config_path or "")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Config file not found: {body.config_path}")

    config = _load_yaml_config(config_path)
    return _save_existing_config(request, config=config, source=body.source, name=body.name)
