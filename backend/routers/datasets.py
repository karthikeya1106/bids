"""
Dataset registry API: list, inspect, activate and delete a workspace's datasets.

Switching a dataset rebuilds the native tables from that dataset's stored
canonical rows, so an older upload can be analysed again without re-uploading.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import DatasetMeta
from security import require_user
from services.capabilities import build_capabilities
from services.ingestion import (
    active_dataset,
    delete_dataset,
    dataset_payload,
    get_dataset,
    set_active,
)
from services.reclassify import ReclassifyError, reclassify_dataset
from services.schemas import SCHEMAS

router = APIRouter()


class TargetRequest(BaseModel):
    target: Optional[str] = None
    task: Optional[str] = None


class ReclassifyRequest(BaseModel):
    # Optional explicit template; omitted means "use the current classifier".
    # Exposed as ``schema`` in JSON, stored as ``template`` to avoid shadowing
    # BaseModel.schema.
    model_config = ConfigDict(populate_by_name=True)

    template: Optional[str] = Field(default=None, alias="schema")


@router.get("")
def list_datasets(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    rows = (
        db.query(DatasetMeta)
        .filter(DatasetMeta.owner_id == owner)
        .order_by(DatasetMeta.is_active.desc(), DatasetMeta.id.desc())
        .all()
    )
    return {
        "datasets": [dataset_payload(row) for row in rows],
        "active_id": next((row.id for row in rows if row.is_active), None),
        "templates": [
            {"id": schema_id, "label": schema.label}
            for schema_id, schema in SCHEMAS.items()
        ],
    }


@router.get("/active/capabilities")
def active_capabilities(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    """What the active dataset can support, computed from its committed rows."""
    meta = active_dataset(db, owner)
    if meta is None:
        raise HTTPException(status_code=404, detail="No active dataset. Upload one first.")
    capabilities, _ = build_capabilities(db, owner, meta)
    return capabilities


@router.patch("/{dataset_id}/target")
def set_target(
    dataset_id: int,
    body: TargetRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Confirm (or clear) the supervised target used by the analytics modules."""
    meta = get_dataset(db, owner, dataset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    capabilities, frame = build_capabilities(db, owner, meta)
    if frame.empty:
        raise HTTPException(status_code=400, detail="The dataset has no stored rows.")

    target = (body.target or "").strip()
    if target:
        if target not in frame.columns:
            raise HTTPException(status_code=422, detail=f"Column '{target}' is not part of this dataset.")
        series = frame[target].dropna()
        classes = int(series.nunique())
        is_numeric = bool(series.dtype.kind in "fiub")
        if classes < 2:
            raise HTTPException(
                status_code=422,
                detail=f"'{target}' has a single value, so it cannot be predicted.",
            )
        if classes <= 20:
            inferred = "classification"
            if classes > 10 and len(series) < 200:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{target}' has {classes} classes in {len(series)} rows — too few rows per class.",
                )
        elif is_numeric:
            inferred = "regression"
        else:
            raise HTTPException(
                status_code=422,
                detail=f"'{target}' has {classes} distinct text values; a target needs 2–20 classes or a numeric measure.",
            )
        task = body.task or inferred
        if task not in {"classification", "regression"}:
            raise HTTPException(status_code=422, detail="task must be classification or regression")
        if task == "classification" and classes > 20:
            raise HTTPException(status_code=422, detail="A classification target needs at most 20 classes.")
        if task == "regression" and not is_numeric:
            raise HTTPException(status_code=422, detail="A regression target must be numeric.")
        meta.target_field = target
        meta.analysis_task = task
    else:
        meta.target_field = None
        meta.analysis_task = "eda"

    db.commit()
    db.refresh(meta)

    refreshed, _ = build_capabilities(db, owner, meta)
    meta.capabilities_json = json.dumps(refreshed, default=str)
    db.commit()

    return {
        "success": True,
        "dataset": dataset_payload(meta),
        "target": refreshed.get("target"),
        "capabilities": refreshed,
        "message": (
            f"Confirmed '{target}' as the {meta.analysis_task} target."
            if target else "Target cleared; the dataset is back to descriptive analysis."
        ),
    }


@router.get("/{dataset_id}")
def get_dataset_detail(
    dataset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = get_dataset(db, owner, dataset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset_payload(meta, include_profile=True)


@router.post("/{dataset_id}/activate")
def activate_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = set_active(db, owner, dataset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return {
        "success": True,
        "dataset": dataset_payload(meta),
        "message": f"Activated '{meta.dataset_name}'. Analytics now use this dataset.",
    }


@router.post("/{dataset_id}/reclassify")
def reclassify_existing_dataset(
    dataset_id: int,
    body: Optional[ReclassifyRequest] = None,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Re-run profiling, classification and mapping on a dataset already stored.

    The stored rows are the source, so the original file is not needed. Any
    refusal (missing fields, failed validation) returns an error and leaves the
    dataset untouched.
    """
    try:
        return reclassify_dataset(db, owner, dataset_id, (body.template if body else None) or None)
    except ReclassifyError as exc:
        detail = {"message": exc.message, **exc.details}
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.delete("/{dataset_id}")
def remove_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    if not delete_dataset(db, owner, dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return {"success": True, "message": "Dataset deleted."}
