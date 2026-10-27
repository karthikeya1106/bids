"""Native analytics for subscriber-churn datasets."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from db.models import ChurnSubscriber
from services.analytics import money

CHURN_COLUMNS = [
    "subscriber_id", "state", "tenure", "area_code",
    "intl_plan", "voicemail_plan", "voicemail_msgs",
    "day_mins", "day_calls", "day_charge",
    "eve_mins", "eve_calls", "eve_charge",
    "night_mins", "night_calls", "night_charge",
    "intl_mins", "intl_calls", "intl_charge",
    "service_calls", "churn_status", "total_charge",
]


def load_churn_df(db: Session, owner_id: str) -> pd.DataFrame:
    rows = db.query(ChurnSubscriber).filter(ChurnSubscriber.owner_id == owner_id).all()
    if not rows:
        return pd.DataFrame(columns=CHURN_COLUMNS)
    return pd.DataFrame(
        [
            {
                "subscriber_id": r.subscriber_id,
                "state": r.state or "Unknown",
                "tenure": int(r.tenure or 0),
                "area_code": r.area_code or "Unknown",
                "intl_plan": str(r.intl_plan or "No"),
                "voicemail_plan": str(r.voicemail_plan or "No"),
                "voicemail_msgs": int(r.voicemail_msgs or 0),
                "day_mins": float(r.day_mins or 0),
                "day_calls": int(r.day_calls or 0),
                "day_charge": float(r.day_charge or 0),
                "eve_mins": float(r.eve_mins or 0),
                "eve_calls": int(r.eve_calls or 0),
                "eve_charge": float(r.eve_charge or 0),
                "night_mins": float(r.night_mins or 0),
                "night_calls": int(r.night_calls or 0),
                "night_charge": float(r.night_charge or 0),
                "intl_mins": float(r.intl_mins or 0),
                "intl_calls": int(r.intl_calls or 0),
                "intl_charge": float(r.intl_charge or 0),
                "service_calls": int(r.service_calls or 0),
                "churn_status": r.churn_status or "Unknown",
                "total_charge": float(r.total_charge or 0),
            }
            for r in rows
        ]
    )


def _is_churned(series: pd.Series) -> pd.Series:
    return series.str.lower().isin(["churned", "true", "yes", "1"])


def _churn_rate(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    return round(float(_is_churned(frame["churn_status"]).mean() * 100), 1)


def _band_table(df: pd.DataFrame, labels: list[tuple[str, pd.Series]]) -> list[dict]:
    rows = []
    for label, mask in labels:
        subset = df[mask]
        rows.append(
            {
                "band": label,
                "subscribers": int(len(subset)),
                "churned": int(_is_churned(subset["churn_status"]).sum()) if len(subset) else 0,
                "churn_rate": _churn_rate(subset),
                "avg_charge": money(subset["total_charge"].mean() if len(subset) else 0),
            }
        )
    return rows


def churn_behavior(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "has_data": False,
            "dataset_type": "churn",
            "mode": "churn",
            "compatible": True,
            "summary": {},
            "churn": None,
            "generated_at": datetime.utcnow().isoformat(),
        }

    churned = _is_churned(df["churn_status"])
    n = len(df)
    churn_count = int(churned.sum())
    active_count = n - churn_count

    tenure_bands = _band_table(
        df,
        [
            ("0–12 months", df["tenure"] <= 12),
            ("13–24 months", (df["tenure"] > 12) & (df["tenure"] <= 24)),
            ("25–48 months", (df["tenure"] > 24) & (df["tenure"] <= 48)),
            ("49+ months", df["tenure"] > 48),
        ],
    )
    service_bands = _band_table(
        df,
        [
            ("0 calls", df["service_calls"] == 0),
            ("1–2 calls", (df["service_calls"] >= 1) & (df["service_calls"] <= 2)),
            ("3–4 calls", (df["service_calls"] >= 3) & (df["service_calls"] <= 4)),
            ("5+ calls", df["service_calls"] >= 5),
        ],
    )

    plan_rows = []
    for col, label in [("intl_plan", "International plan"), ("voicemail_plan", "Voicemail plan")]:
        for value, grp in df.groupby(df[col].astype(str)):
            plan_rows.append(
                {
                    "plan": f"{label}: {value}",
                    "subscribers": int(len(grp)),
                    "churn_rate": _churn_rate(grp),
                    "avg_charge": money(grp["total_charge"].mean()),
                }
            )

    by_state = (
        df.groupby("state")
        .agg(
            subscribers=("subscriber_id", "count"),
            avg_charge=("total_charge", "mean"),
            avg_tenure=("tenure", "mean"),
            avg_service_calls=("service_calls", "mean"),
        )
        .reset_index()
    )
    churned_by_state = df[churned].groupby("state")["subscriber_id"].count() if churn_count else pd.Series(dtype=int)
    state_rows = []
    for _, row in by_state.sort_values("subscribers", ascending=False).head(12).iterrows():
        churned_n = int(churned_by_state.get(row["state"], 0))
        state_rows.append(
            {
                "state": row["state"],
                "subscribers": int(row["subscribers"]),
                "churned": churned_n,
                "churn_rate": round(churned_n / row["subscribers"] * 100, 1) if row["subscribers"] else 0.0,
                "avg_charge": money(row["avg_charge"]),
                "avg_tenure": round(float(row["avg_tenure"]), 1),
            }
        )

    return {
        "has_data": True,
        "dataset_type": "churn",
        "mode": "churn",
        "compatible": True,
        "summary": {
            "subscribers": n,
            "churned": churn_count,
            "active": active_count,
            "churn_rate": round(churn_count / n * 100, 1) if n else 0.0,
            "avg_tenure": round(float(df["tenure"].mean()), 1),
            "avg_charge": money(df["total_charge"].mean()),
            "avg_service_calls": round(float(df["service_calls"].mean()), 2),
            "total_charge": money(df["total_charge"].sum()),
        },
        "churn": {
            "tenure_bands": tenure_bands,
            "service_bands": service_bands,
            "plans": plan_rows,
            "by_state": state_rows,
            "charge_mix": {
                "day": money(df["day_charge"].sum()),
                "eve": money(df["eve_charge"].sum()),
                "night": money(df["night_charge"].sum()),
                "intl": money(df["intl_charge"].sum()),
            },
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


def churn_segments(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "has_data": False,
            "dataset_type": "churn",
            "mode": "churn",
            "compatible": True,
            "segments": [],
            "top_customers": [],
            "total_customers": 0,
            "total_revenue": 0.0,
            "averages": {},
        }

    churned = _is_churned(df["churn_status"])
    work = df.copy()
    work["segment"] = ["Churned" if flag else "Active" for flag in churned]
    high_touch = (~churned) & (work["service_calls"] >= 4)
    work.loc[high_touch, "segment"] = "High-touch Active"

    labels = {
        "Active": {
            "color": "#111111",
            "description": "Subscribers still on the network.",
        },
        "High-touch Active": {
            "color": "#6b7280",
            "description": "Active accounts with four or more service calls — elevated churn risk.",
        },
        "Churned": {
            "color": "#9ca3af",
            "description": "Accounts marked churned in the source file.",
        },
    }

    total_charge = float(work["total_charge"].sum())
    segments = []
    for name in ["Active", "High-touch Active", "Churned"]:
        group = work[work["segment"] == name]
        if group.empty:
            continue
        charge = float(group["total_charge"].sum())
        meta = labels[name]
        segments.append(
            {
                "name": name,
                "color": meta["color"],
                "description": meta["description"],
                "count": int(len(group)),
                "share": round(len(group) / len(work) * 100, 1),
                "revenue": money(charge),
                "revenue_share": round(charge / total_charge * 100, 1) if total_charge else 0.0,
                "avg_monetary": money(group["total_charge"].mean()),
                "avg_frequency": round(float(group["tenure"].mean()), 1),
                "avg_recency": round(float(group["service_calls"].mean()), 1),
                "avg_order_value": money(group["total_charge"].mean()),
                "avg_quantity": round(float(group["tenure"].mean()), 1),
                "avg_discount": 0.0,
                "inactive_share": round(float(_is_churned(group["churn_status"]).mean() * 100), 1),
                "top_category": "Tenure (months)",
                "top_region": group["state"].mode().iloc[0] if not group["state"].mode().empty else "—",
            }
        )

    top = (
        work.sort_values("total_charge", ascending=False)
        .head(15)
        [
            [
                "subscriber_id",
                "state",
                "segment",
                "tenure",
                "service_calls",
                "total_charge",
                "churn_status",
            ]
        ]
        .rename(
            columns={
                "subscriber_id": "customer_id",
                "state": "region",
                "tenure": "frequency",
                "total_charge": "monetary",
            }
        )
    )
    top["customer_name"] = top["customer_id"]
    top["account_segment"] = top["churn_status"]
    top["recency"] = work.loc[top.index, "service_calls"].values
    top["avg_order_value"] = top["monetary"]
    top["top_category"] = "Observed charges"

    return {
        "has_data": True,
        "dataset_type": "churn",
        "mode": "churn",
        "compatible": True,
        "segments": segments,
        "top_customers": top.to_dict(orient="records"),
        "total_customers": int(len(work)),
        "total_revenue": money(total_charge),
        "averages": {
            "recency": round(float(work["service_calls"].mean()), 1),
            "frequency": round(float(work["tenure"].mean()), 1),
            "monetary": money(work["total_charge"].mean()),
            "order_value": money(work["total_charge"].mean()),
        },
        "value_note": "Monetary figures are observed usage charges, not sales revenue.",
    }
