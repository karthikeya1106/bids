"""
Module dispatcher for dataset-adaptive analytics.

Each module router calls this for datasets that are not sales transaction
history. The dispatcher resolves the active dataset, its capabilities and the
committed frame once, then hands off to the module implementation.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from services import cache
from services.capabilities import build_capabilities, prepare_frame
from services.ingestion import active_dataset, get_dataset
from services.modules_descriptive import behavior_module, dashboard_module, segmentation_module
from services.modules_diagnostic import drift_module, rootcause_module
from services.modules_predictive import forecast_module, strategy_module

MODULE_BUILDERS = {
    "dashboard": dashboard_module,
    "behavior": behavior_module,
    "segmentation": segmentation_module,
    "rootcause": rootcause_module,
    "forecast": forecast_module,
    "strategy": strategy_module,
}


def build_module(
    db: Session,
    owner_id: str,
    module: str,
    reference_id: Optional[int] = None,
    caps: Optional[dict] = None,
    frame: Optional[pd.DataFrame] = None,
) -> dict:
    """Compose the adaptive payload for one module."""
    cache_key = None
    if caps is None or frame is None:
        meta = active_dataset(db, owner_id)
        signature = cache.dataset_signature(meta)
        cache_key = (signature, module, reference_id) if signature else None
        cached = cache.get_payload(cache_key)
        if cached is not None:
            return cached
        caps, frame = build_capabilities(db, owner_id, meta)

    if module not in MODULE_BUILDERS and module != "drift":
        raise ValueError(f"Unknown module '{module}'")

    if frame is None or frame.empty:
        return {
            "has_data": False,
            "compatible": True,
            "mode": "adaptive",
            "module": module,
            "status": "unavailable",
            "dataset": caps.get("dataset"),
            "summary": [],
            "sections": [],
            "insights": [],
            "limitations": ["The active dataset has no stored rows."],
            "requires": ["Re-upload the dataset or activate another one."],
        }

    if module == "drift":
        reference_frame = None
        reference_label = None
        if reference_id is not None:
            reference_meta = get_dataset(db, owner_id, reference_id)
            active = active_dataset(db, owner_id)
            if reference_meta is not None and active is not None and reference_meta.id != active.id:
                raw = None
                from services.capabilities import load_frame

                raw = load_frame(db, owner_id, reference_meta)
                if not raw.empty:
                    reference_frame = prepare_frame(raw)
                    reference_label = reference_meta.dataset_name
        payload = drift_module(frame, caps, reference_frame, reference_label)
        cache.put_payload(cache_key, payload)
        return payload

    payload = MODULE_BUILDERS[module](frame, caps)
    cache.put_payload(cache_key, payload)
    return payload
