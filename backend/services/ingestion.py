"""
Ingestion and dataset registry.

Uploaded data is converted into canonical records (mapped fields only, plus
clearly labelled derivations) and stored per dataset. Sales and churn datasets
are additionally materialised into the native tables that power the existing
modules, and a dataset can be re-activated later.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    BPRRule,
    ChurnSubscriber,
    Customer,
    DatasetMeta,
    DatasetRow,
    KPI,
    Order,
)
from services.mapping import GENERATE, apply_derivation, coerce_value
from services.schemas import DATETIME, NUMERIC, SCHEMAS, DatasetSchema, get_schema

MAX_STORED_ROWS = 200_000


# ─── Serialisation ────────────────────────────────────────────────────────────

def _loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dataset_payload(meta: DatasetMeta, include_profile: bool = False) -> dict:
    schema = get_schema(meta.schema_kind)
    capabilities = _loads(meta.capabilities_json, {}) or {}
    classification = capabilities.get("classification") or {}
    payload = {
        "id": meta.id,
        "name": meta.dataset_name,
        "org_name": meta.org_name,
        "schema": meta.schema_kind,
        "schema_label": schema.label,
        "task": meta.analysis_task,
        "target": meta.target_field,
        "rows": meta.row_count or 0,
        "customers": meta.customer_count or 0,
        "total_sales": meta.total_sales or 0.0,
        "is_active": bool(meta.is_active),
        "materialized": bool(meta.materialized),
        "synthetic_identifiers": bool(meta.synthesized),
        "uploaded_at": str(meta.uploaded_at) if meta.uploaded_at else None,
        "validation": _loads(meta.validation_json, {}),
        "capabilities": capabilities,
        "mapping": _loads(meta.mapping_json, {}),
        # Classification provenance: present for datasets that were (re)classified
        # by the current pipeline, absent on older registrations.
        "confidence": classification.get("confidence"),
        "needs_review": bool(classification.get("ambiguous")),
        "classified_at": classification.get("classified_at"),
        "supported_tasks": classification.get("supported_tasks") or {},
    }
    if include_profile:
        payload["profile"] = _loads(meta.profile_json, {})
        payload["schema_definition"] = _loads(meta.schema_json, schema.to_payload())
    return payload


def active_dataset(db: Session, owner_id: str) -> Optional[DatasetMeta]:
    return (
        db.query(DatasetMeta)
        .filter(DatasetMeta.owner_id == owner_id, DatasetMeta.is_active == 1)
        .order_by(DatasetMeta.id.desc())
        .first()
    )


def get_dataset(db: Session, owner_id: str, dataset_id: int) -> Optional[DatasetMeta]:
    return (
        db.query(DatasetMeta)
        .filter(DatasetMeta.owner_id == owner_id, DatasetMeta.id == dataset_id)
        .first()
    )


# ─── Canonical records ────────────────────────────────────────────────────────

def build_records(
    df: pd.DataFrame,
    schema: DatasetSchema,
    mapping: dict[str, str],
) -> tuple[list[dict], int, int]:
    """Convert the raw frame into canonical records.

    Returns (records, generated_identifier_count, skipped_rows). Missing values
    are left empty — nothing is fabricated except a labelled technical row key
    when the schema explicitly allows one.
    """
    records: list[dict] = []
    generated = 0
    skipped = 0

    if schema.id == "generic":
        typed: dict[str, str] = {}
        profile_types = {column.name: column for column in []}  # placeholder
        for column in df.columns:
            series = df[column]
            if pd.api.types.is_numeric_dtype(series):
                typed[column] = NUMERIC
            elif pd.api.types.is_datetime64_any_dtype(series):
                typed[column] = DATETIME
        for index, row in enumerate(df.to_dict(orient="records")):
            record = {
                str(column): coerce_value(value, typed.get(column, "text"))
                for column, value in row.items()
            }
            record["__row__"] = index + 1
            records.append(record)
        return records, 0, 0

    fields = schema.field_map()
    resolved: list[tuple[str, str, Any]] = []
    for key, spec in fields.items():
        if spec.derive:
            continue
        value = mapping.get(key)
        if not value:
            continue
        if value == GENERATE:
            resolved.append((key, spec.dtype, GENERATE))
            continue
        if value in df.columns:
            resolved.append((key, spec.dtype, value))

    for index, row in enumerate(df.to_dict(orient="records")):
        record: dict[str, Any] = {}
        for key, dtype, source in resolved:
            if source == GENERATE:
                record[key] = f"ROW-{index + 1:06d}"
                generated += 1
                continue
            converted = coerce_value(row.get(source), dtype)
            if converted is None and dtype in (NUMERIC, DATETIME) and fields[key].required:
                skipped += 1
                record = {}
                break
            record[key] = converted

        if not record:
            continue

        for key, spec in fields.items():
            if not spec.derive:
                continue
            value = apply_derivation(spec.derive, record)
            if value is not None:
                record[key] = value

        record.setdefault("__row__", index + 1)
        records.append(record)

    return records, generated, skipped


# ─── Native materialisation ───────────────────────────────────────────────────

def clear_native_tables(db: Session, owner_id: str) -> None:
    db.query(Order).filter(Order.owner_id == owner_id).delete()
    db.query(Customer).filter(Customer.owner_id == owner_id).delete()
    db.query(ChurnSubscriber).filter(ChurnSubscriber.owner_id == owner_id).delete()
    db.query(KPI).filter(KPI.owner_id == owner_id).delete()
    db.query(BPRRule).filter(BPRRule.owner_id == owner_id).delete()
    db.commit()


def _date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    number = _float(value)
    if number is None:
        return None
    return int(round(number))


def normalize_churn_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "churned", "churn", "left", "canceled", "cancelled", "attrition"}:
        return "Churned"
    if text in {"false", "0", "no", "n", "active", "retained", "stayed", "current"}:
        return "Active"
    return str(value).strip().title() or "Unknown"


def materialize_native(db: Session, owner_id: str, meta: DatasetMeta, records: list[dict]) -> int:
    """Rebuild the native tables for a sales or churn dataset."""
    clear_native_tables(db, owner_id)

    if meta.schema_kind == "sales":
        customer_rows: dict[str, Customer] = {}
        orders: list[Order] = []
        for record in records:
            order_date = _date(record.get("order_date"))
            sales = _float(record.get("sales"))
            if order_date is None or sales is None:
                continue
            quantity = _int(record.get("quantity"))
            discount = _float(record.get("discount"))
            if discount is not None and discount > 1:
                discount = discount / 100.0
            orders.append(
                Order(
                    owner_id=owner_id,
                    order_id=str(record.get("order_id") or f"ORD-{len(orders) + 1:06d}"),
                    order_date=order_date,
                    ship_date=_date(record.get("ship_date")),
                    customer_id=str(record.get("customer_id") or "") or None,
                    category=record.get("category"),
                    sub_category=record.get("sub_category"),
                    product_name=record.get("product_name"),
                    sales=sales,
                    quantity=quantity,
                    discount=discount,
                    profit=_float(record.get("profit")),
                )
            )
            customer_id = str(record.get("customer_id") or "").strip()
            if customer_id and customer_id not in customer_rows:
                customer_rows[customer_id] = Customer(
                    owner_id=owner_id,
                    customer_id=customer_id,
                    customer_name=record.get("customer_name") or customer_id,
                    segment=record.get("segment"),
                    region=record.get("region"),
                    city=record.get("city"),
                    state=record.get("state"),
                    country=record.get("region"),
                )

        for start in range(0, len(orders), 2000):
            db.bulk_save_objects(orders[start:start + 2000])
            db.commit()
        customers = list(customer_rows.values())
        for start in range(0, len(customers), 2000):
            db.bulk_save_objects(customers[start:start + 2000])
            db.commit()
        db.commit()
        return len(orders)

    if meta.schema_kind == "churn":
        rows: list[ChurnSubscriber] = []
        for index, record in enumerate(records):
            total = _float(record.get("total_charge"))
            derived_total = _float(record.get("total_charge_derived"))
            if total is None:
                total = derived_total
            rows.append(
                ChurnSubscriber(
                    owner_id=owner_id,
                    subscriber_id=str(record.get("subscriber_id") or f"ROW-{index + 1:06d}"),
                    state=record.get("state"),
                    tenure=_int(record.get("tenure")),
                    area_code=record.get("area_code"),
                    intl_plan=record.get("intl_plan"),
                    voicemail_plan=record.get("voicemail_plan"),
                    voicemail_msgs=_int(record.get("voicemail_msgs")),
                    day_mins=_float(record.get("day_mins")),
                    day_calls=_int(record.get("day_calls")),
                    day_charge=_float(record.get("day_charge")),
                    eve_mins=_float(record.get("eve_mins")),
                    eve_calls=_int(record.get("eve_calls")),
                    eve_charge=_float(record.get("eve_charge")),
                    night_mins=_float(record.get("night_mins")),
                    night_calls=_int(record.get("night_calls")),
                    night_charge=_float(record.get("night_charge")),
                    intl_mins=_float(record.get("intl_mins")),
                    intl_calls=_int(record.get("intl_calls")),
                    intl_charge=_float(record.get("intl_charge")),
                    service_calls=_int(record.get("service_calls")),
                    churn_status=normalize_churn_label(record.get("churn_status")),
                    total_charge=total,
                )
            )
        for start in range(0, len(rows), 2000):
            db.bulk_save_objects(rows[start:start + 2000])
            db.commit()
        db.commit()
        return len(rows)

    return 0


# ─── Registration ─────────────────────────────────────────────────────────────

def create_dataset(
    db: Session,
    owner_id: str,
    df: pd.DataFrame,
    filename: str,
    org_name: Optional[str],
    schema: DatasetSchema,
    mapping: dict[str, str],
    decisions: dict[str, dict],
    task: str,
    target: Optional[str],
    profile: dict,
    validation: dict,
    capabilities: dict,
    modules: dict,
) -> DatasetMeta:
    """Persist canonical records, register the dataset and activate it."""
    if len(df) > MAX_STORED_ROWS:
        raise ValueError(f"Dataset has {len(df):,} rows; the limit is {MAX_STORED_ROWS:,}.")

    records, generated, skipped = build_records(df, schema, mapping)
    if not records:
        raise ValueError(
            "No usable rows could be read. Check the required field mappings and value formats."
        )

    db.query(DatasetMeta).filter(DatasetMeta.owner_id == owner_id).update({DatasetMeta.is_active: 0})
    db.commit()

    sales_total = 0.0
    if schema.id == "sales":
        sales_total = sum(float(record.get("sales") or 0) for record in records)
    elif schema.id == "churn":
        sales_total = sum(
            float(record.get("total_charge") or record.get("total_charge_derived") or 0)
            for record in records
        )

    meta = DatasetMeta(
        owner_id=owner_id,
        dataset_name=filename,
        org_name=(org_name or "").strip() or None,
        source="upload",
        dataset_type=schema.id,
        schema_kind=schema.id,
        analysis_task=task,
        target_field=target,
        synthesized=1 if generated else 0,
        row_count=len(records),
        customer_count=len({
            str(record.get("customer_id") or record.get("subscriber_id"))
            for record in records
            if record.get("customer_id") or record.get("subscriber_id")
        }),
        total_sales=round(sales_total, 2),
        is_active=1,
        materialized=0,
        profile_json=json.dumps(profile, default=str),
        mapping_json=json.dumps(decisions, default=str),
        schema_json=json.dumps(schema.to_payload(), default=str),
        validation_json=json.dumps(
            {
                "ready": validation.get("ready"),
                "errors": validation.get("errors"),
                "warnings": validation.get("warnings"),
                "checks": validation.get("checks", []),
                "forecast": validation.get("forecast"),
                "notes": _notes_for(schema, validation, target, task),
                "skipped_rows": skipped,
            },
            default=str,
        ),
        capabilities_json=json.dumps({**capabilities, "modules": modules}, default=str),
        uploaded_at=datetime.utcnow(),
    )
    db.add(meta)
    db.commit()
    db.refresh(meta)

    for start in range(0, len(records), 2000):
        db.bulk_insert_mappings(
            DatasetRow,
            [
                {
                    "owner_id": owner_id,
                    "dataset_id": meta.id,
                    "row_index": start + offset + 1,
                    "payload": record,
                }
                for offset, record in enumerate(records[start:start + 2000])
            ],
        )
        db.commit()

    materialized = materialize_native(db, owner_id, meta, records)
    meta.materialized = 1 if materialized else 0
    if schema.id == "sales":
        from services.analytics import recalculate_kpis
        from seed_bpr import ensure_bpr_rules

        recalculate_kpis(db, owner_id)
        ensure_bpr_rules(db, owner_id)
    db.commit()
    return meta


def _notes_for(
    schema: DatasetSchema,
    validation: dict,
    target: Optional[str],
    task: str,
) -> list[str]:
    notes = []
    capabilities = validation.get("capabilities", {})
    if schema.id == "sales":
        if not capabilities.get("has_profit"):
            notes.append("Profit was not mapped, so margin metrics are unavailable.")
        if not capabilities.get("has_customer"):
            notes.append("No customer identifier was mapped, so cohort and retention views are unavailable.")
        if not capabilities.get("has_discount"):
            notes.append("Discount was not mapped, so discount-impact analysis is unavailable.")
    if task == "forecast" and validation.get("forecast") and not validation["forecast"].get("available"):
        notes.append("Forecast is unavailable: " + "; ".join(validation["forecast"].get("reasons", [])))
    if not target:
        notes.append("No supervised target was selected; the report will use profiling and unsupervised analysis.")
    return notes


def set_active(db: Session, owner_id: str, dataset_id: int) -> Optional[DatasetMeta]:
    """Switch the workspace to another stored dataset and rebuild native tables."""
    meta = get_dataset(db, owner_id, dataset_id)
    if meta is None:
        return None

    db.query(DatasetMeta).filter(DatasetMeta.owner_id == owner_id).update({DatasetMeta.is_active: 0})
    meta.is_active = 1
    db.commit()

    rows = (
        db.query(DatasetRow)
        .filter(DatasetRow.owner_id == owner_id, DatasetRow.dataset_id == meta.id)
        .order_by(DatasetRow.row_index)
        .all()
    )
    records = [row.payload for row in rows]
    materialized = materialize_native(db, owner_id, meta, records)
    meta.materialized = 1 if materialized else 0
    db.commit()

    if meta.schema_kind == "sales" and records:
        from services.analytics import recalculate_kpis
        from seed_bpr import ensure_bpr_rules

        recalculate_kpis(db, owner_id)
        ensure_bpr_rules(db, owner_id)
    return meta


def delete_dataset(db: Session, owner_id: str, dataset_id: int) -> bool:
    meta = get_dataset(db, owner_id, dataset_id)
    if meta is None:
        return False
    was_active = bool(meta.is_active)
    db.query(DatasetRow).filter(
        DatasetRow.owner_id == owner_id, DatasetRow.dataset_id == dataset_id
    ).delete()
    db.delete(meta)
    db.commit()

    if was_active:
        newest = (
            db.query(DatasetMeta)
            .filter(DatasetMeta.owner_id == owner_id)
            .order_by(DatasetMeta.id.desc())
            .first()
        )
        if newest:
            set_active(db, owner_id, newest.id)
        else:
            clear_native_tables(db, owner_id)
    return True


def records_frame(db: Session, owner_id: str, dataset_id: int) -> pd.DataFrame:
    # Select only the payload column. Building one ORM entity per stored record
    # costs several times more than the JSON parse itself on large uploads.
    payloads = (
        db.execute(
            select(DatasetRow.payload)
            .where(DatasetRow.owner_id == owner_id, DatasetRow.dataset_id == dataset_id)
            .order_by(DatasetRow.row_index)
        )
        .scalars()
        .all()
    )
    if not payloads:
        return pd.DataFrame()
    return pd.DataFrame(payloads)
