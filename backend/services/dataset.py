"""
Workspace dataset identity and module gating.

The analytics modules were written for sales transaction history. They must not
run on a churn, HR or generic dataset and silently present zeroes as if they were
real metrics, so every module asks this helper whether the active dataset is
compatible and returns an explanation instead when it is not.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from db.models import BPRRule, ChurnSubscriber, Customer, DatasetMeta, KPI, Order
from services.ingestion import active_dataset, dataset_payload
from services.schemas import get_schema

SALES_MODULES = {"dashboard", "rootcause", "drift", "forecast", "strategy"}
CUSTOMER_MODULES = {"behavior", "segmentation"}

SALES_ONLY = (
    "This module analyses sales transaction history — orders, revenue, margins "
    "and multi-period timelines. The active dataset is {label}, so those numbers "
    "are not computed. Open the Analysis Report for the analyses this dataset "
    "actually supports, or upload a sales export."
)

CUSTOMER_ONLY = (
    "This module needs one row per customer with a churn label or repeat purchase "
    "history. The active dataset is {label}. Open the Analysis Report to see what "
    "is supported."
)


def get_active_meta(db: Session, owner_id: str) -> Optional[DatasetMeta]:
    return active_dataset(db, owner_id)


def workspace_profile(db: Session, owner_id: str) -> dict:
    """Cheap summary of the active dataset (no payload parsing)."""
    meta = active_dataset(db, owner_id)
    order_count = db.query(Order).filter(Order.owner_id == owner_id).count()
    subscriber_count = (
        db.query(ChurnSubscriber).filter(ChurnSubscriber.owner_id == owner_id).count()
    )
    schema_id = meta.schema_kind if meta else "generic"

    return {
        "meta": meta,
        "schema": schema_id,
        "dataset_type": "churn" if schema_id == "churn" else "sales" if schema_id == "sales" else schema_id,
        "has_data": bool(meta and meta.row_count) or order_count > 0 or subscriber_count > 0,
        "order_count": order_count,
        "subscriber_count": subscriber_count,
        "synthesized": bool(meta.synthesized) if meta else False,
    }


def _incompatible(meta: Optional[DatasetMeta], module: str, message: str) -> dict:
    label = get_schema(meta.schema_kind if meta else None).label
    payload = dataset_payload(meta) if meta else None
    modules = (payload or {}).get("capabilities", {}).get("modules", {})
    return {
        "has_data": False,
        "compatible": False,
        "dataset_type": meta.schema_kind if meta else None,
        "module": module,
        "message": message.format(label=label),
        "dataset": (
            {
                "id": meta.id,
                "name": meta.dataset_name,
                "schema": meta.schema_kind,
                "schema_label": label,
            }
            if meta
            else None
        ),
        "modules": modules,
    }


def gate_module(db: Session, owner_id: str, module: str) -> Optional[dict]:
    """Return an explanation payload when the active dataset cannot power a module."""
    meta = active_dataset(db, owner_id)
    schema_id = meta.schema_kind if meta else "generic"

    if module in SALES_MODULES and schema_id != "sales":
        return _incompatible(meta, module, SALES_ONLY)

    if module in CUSTOMER_MODULES and schema_id not in ("sales", "churn"):
        return _incompatible(meta, module, CUSTOMER_ONLY)

    return None


def incompatible_payload(dataset_type: str, extra: Optional[dict] = None) -> dict:
    payload = {
        "has_data": False,
        "compatible": False,
        "dataset_type": dataset_type,
        "message": "This dataset cannot power the requested module.",
    }
    if extra:
        payload.update(extra)
    return payload


def clear_workspace(db: Session, owner_id: str) -> None:
    """Remove every analytical row for a workspace (used by dataset deletion)."""
    db.query(Order).filter(Order.owner_id == owner_id).delete()
    db.query(Customer).filter(Customer.owner_id == owner_id).delete()
    db.query(ChurnSubscriber).filter(ChurnSubscriber.owner_id == owner_id).delete()
    db.query(KPI).filter(KPI.owner_id == owner_id).delete()
    db.query(BPRRule).filter(BPRRule.owner_id == owner_id).delete()
    db.query(DatasetMeta).filter(DatasetMeta.owner_id == owner_id).delete()
    db.commit()
