"""FastAPI router for the first-class dataset service.

Endpoints
---------
POST   /api/datasets                           - create dataset
GET    /api/datasets                           - list datasets
GET    /api/datasets/{dataset_id}              - get dataset info
POST   /api/datasets/{dataset_id}/rows        - add rows
POST   /api/datasets/{dataset_id}/versions    - create version (snapshot)
GET    /api/datasets/{dataset_id}/versions    - list versions
GET    /api/datasets/{dataset_id}/rows        - get rows (?version=X&split=Y)
GET    /api/datasets/{dataset_id}/stats       - quality metrics
POST   /api/datasets/{dataset_id}/import/traces - import from traces
POST   /api/datasets/{dataset_id}/export      - export to JSON
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from data.dataset_service import DatasetService
from data.dataset_store import DatasetStore
from data.dataset_versioning import VersionPin, VersionPinStore

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# ---------------------------------------------------------------------------
# Shared service instance (lazy-initialised singleton)
# ---------------------------------------------------------------------------

_service: Optional[DatasetService] = None
_pin_store: Optional[VersionPinStore] = None


def _get_service() -> DatasetService:
    global _service
    if _service is None:
        _service = DatasetService(store=DatasetStore())
    return _service


def _get_pin_store() -> VersionPinStore:
    global _pin_store
    if _pin_store is None:
        _pin_store = VersionPinStore()
    return _pin_store


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""


class AddRowsRequest(BaseModel):
    rows: list[dict[str, Any]]


class CreateVersionRequest(BaseModel):
    description: str = ""


class ImportTracesRequest(BaseModel):
    traces: list[dict[str, Any]]


class ImportEvalCasesRequest(BaseModel):
    cases: list[dict[str, Any]]


class ExportRequest(BaseModel):
    version_id: Optional[str] = None
    output_path: Optional[str] = None


class ConfigureSplitsRequest(BaseModel):
    splits: dict[str, float]


class SaveVersionPinRequest(BaseModel):
    dataset_version: str
    grader_version: str = ""
    judge_version: str = ""
    config_version: str = ""
    skill_versions: dict[str, str] = {}
    model_version: str = ""
    experiment_id: str = ""
    name: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("")
def create_dataset(req: CreateDatasetRequest) -> dict[str, Any]:
    """Create a new empty dataset."""
    svc = _get_service()
    info = svc.create(name=req.name, description=req.description)
    return info.to_dict()


@router.get("")
def list_datasets() -> list[dict[str, Any]]:
    """List all datasets."""
    svc = _get_service()
    return [ds.to_dict() for ds in svc.list_datasets()]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Get detailed info for a dataset including version list and splits."""
    svc = _get_service()
    info = svc.get(dataset_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    # Attach quality metrics
    info.quality_metrics = svc.compute_quality_metrics(dataset_id)
    return info.to_dict()


@router.post("/{dataset_id}/rows")
def add_rows(dataset_id: str, req: AddRowsRequest) -> dict[str, Any]:
    """Add rows to a dataset (unversioned; call /versions to snapshot)."""
    svc = _get_service()
    # Verify dataset exists
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    ids = svc.store.add_rows(dataset_id, req.rows)
    return {"added": len(ids), "row_ids": ids}


@router.post("/{dataset_id}/versions")
def create_version(dataset_id: str, req: CreateVersionRequest) -> dict[str, Any]:
    """Create an immutable version snapshot of current unversioned rows."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    version = svc.create_version(dataset_id, description=req.description)
    return version.to_dict()


@router.get("/{dataset_id}/versions")
def list_versions(dataset_id: str) -> list[dict[str, Any]]:
    """List all versions for a dataset, newest first."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return [v.to_dict() for v in svc.list_versions(dataset_id)]


@router.get("/{dataset_id}/rows")
def get_rows(
    dataset_id: str,
    version: Optional[str] = Query(default=None, description="Version ID to filter by"),
    split: Optional[str] = Query(default=None, description="Split name to filter by"),
) -> list[dict[str, Any]]:
    """Return rows for a dataset, optionally filtered by version and split."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    rows = svc.get_split(dataset_id, version_id=version, split=split)
    return [r.to_dict() for r in rows]


@router.get("/{dataset_id}/stats")
def get_stats(dataset_id: str) -> dict[str, Any]:
    """Return quality metrics and summary stats for a dataset."""
    svc = _get_service()
    result = svc.stats(dataset_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{dataset_id}/import/traces")
def import_from_traces(dataset_id: str, req: ImportTracesRequest) -> dict[str, Any]:
    """Import rows from agent trace dicts."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    count = svc.import_from_traces(dataset_id, req.traces)
    return {"imported": count, "dataset_id": dataset_id}


@router.post("/{dataset_id}/import/eval-cases")
def import_from_eval_cases(dataset_id: str, req: ImportEvalCasesRequest) -> dict[str, Any]:
    """Import rows from EvalCase dicts."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    count = svc.import_from_eval_cases(dataset_id, req.cases)
    return {"imported": count, "dataset_id": dataset_id}


@router.post("/{dataset_id}/splits")
def configure_splits(dataset_id: str, req: ConfigureSplitsRequest) -> list[dict[str, Any]]:
    """Re-assign split tags to unversioned rows according to given percentages."""
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    splits = svc.configure_splits(dataset_id, req.splits)
    return [s.to_dict() for s in splits]


@router.post("/{dataset_id}/export")
def export_dataset(dataset_id: str, req: ExportRequest) -> dict[str, Any]:
    """Export dataset rows to a JSON file.

    If ``output_path`` is not provided a temporary file is used.
    Returns the path and row count.
    """
    svc = _get_service()
    if not svc.store.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    output_path = req.output_path
    if not output_path:
        suffix = f"_{req.version_id}" if req.version_id else ""
        tmp_dir = tempfile.gettempdir()
        output_path = os.path.join(tmp_dir, f"dataset_{dataset_id}{suffix}.json")

    resolved = svc.export_to_json(dataset_id, req.version_id, output_path)
    row_count = svc.store.count_rows(dataset_id, version_id=req.version_id)
    return {
        "output_path": resolved,
        "row_count": row_count,
        "dataset_id": dataset_id,
        "version_id": req.version_id,
    }


# ---------------------------------------------------------------------------
# Version pin routes (sub-resource of datasets)
# ---------------------------------------------------------------------------


@router.post("/{dataset_id}/pins")
def save_version_pin(dataset_id: str, req: SaveVersionPinRequest) -> dict[str, Any]:
    """Save a VersionPin experiment card for full reproducibility."""
    store = _get_pin_store()
    pin = VersionPin(
        dataset_version=req.dataset_version,
        grader_version=req.grader_version,
        judge_version=req.judge_version,
        config_version=req.config_version,
        skill_versions=req.skill_versions,
        model_version=req.model_version,
    )
    card = store.save_pin(
        pin,
        experiment_id=req.experiment_id or dataset_id,
        name=req.name,
        description=req.description,
    )
    return card.to_dict()


@router.get("/{dataset_id}/pins")
def list_version_pins(dataset_id: str) -> list[dict[str, Any]]:
    """List all VersionPin cards associated with a dataset's experiment_id."""
    store = _get_pin_store()
    cards = store.get_pin_by_experiment(dataset_id)
    return [c.to_dict() for c in cards]


@router.get("/{dataset_id}/pins/{pin_id}")
def get_version_pin(dataset_id: str, pin_id: str) -> dict[str, Any]:
    """Get a specific VersionPin by its pin_id."""
    store = _get_pin_store()
    card = store.get_pin(pin_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Pin '{pin_id}' not found")
    return card.to_dict()
