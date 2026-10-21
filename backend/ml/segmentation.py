"""
Customer Segmentation: RFM scoring + K-Means clustering
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from datetime import date


SEGMENT_LABELS = {
    0: {"name": "Champions",    "color": "#10b981", "description": "High value, frequent buyers, recent purchases"},
    1: {"name": "At-Risk",      "color": "#f59e0b", "description": "Past high-spenders now going inactive"},
    2: {"name": "New / Growing","color": "#6366f1", "description": "Recent buyers with growing potential"},
    3: {"name": "Lost",         "color": "#ef4444", "description": "Inactive customers, low frequency and spend"},
}


def compute_rfm(orders_df: pd.DataFrame, snapshot_date=None) -> pd.DataFrame:
    """
    Compute Recency, Frequency, Monetary scores per customer.

    Args:
        orders_df: DataFrame with [order_date, order_id, customer_id, sales].
        snapshot_date: Reference date for recency. Defaults to the latest order date.
    """
    orders_df = orders_df.copy()
    orders_df["order_date"] = pd.to_datetime(orders_df["order_date"])

    if snapshot_date is None:
        snap = orders_df["order_date"].max()
    else:
        # Ensure idempotent — works whether snapshot_date is a date, str, or Timestamp
        snap = pd.Timestamp(snapshot_date)

    rfm = orders_df.groupby("customer_id").agg(
        recency=("order_date", lambda x: (snap - x.max()).days),
        frequency=("order_id", "nunique"),
        monetary=("sales", "sum"),
    ).reset_index()

    rfm["recency"] = rfm["recency"].clip(upper=730)
    rfm["monetary"] = rfm["monetary"].round(2)
    return rfm


def run_segmentation(orders_df: pd.DataFrame) -> dict:
    rfm = compute_rfm(orders_df)

    scaler = StandardScaler()
    rfm_scaled = scaler.fit_transform(rfm[["recency", "frequency", "monetary"]])

    n_clusters = min(4, len(rfm))  # guard against tiny datasets
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    rfm["cluster"] = kmeans.fit_predict(rfm_scaled)

    # Map clusters to meaningful labels by inspecting centroids
    centers = pd.DataFrame(
        scaler.inverse_transform(kmeans.cluster_centers_),
        columns=["recency", "frequency", "monetary"],
    )
    # Champion: low recency, high freq, high monetary
    centers["score"] = -centers["recency"] + centers["frequency"] * 2 + centers["monetary"] / 500
    sorted_clusters = centers["score"].argsort()[::-1].values  # best first

    # Build mapping: original cluster_id → SEGMENT_LABELS key (0=Champions … 3=Lost)
    label_map = {}
    for rank, cluster_id in enumerate(sorted_clusters):
        label_map[int(cluster_id)] = rank % 4  # wrap in case n_clusters < 4

    rfm["segment_id"] = rfm["cluster"].map(label_map)
    rfm["segment"] = rfm["segment_id"].map(lambda x: SEGMENT_LABELS[x]["name"])

    # Build segment summary
    segment_summary = []
    for sid, info in SEGMENT_LABELS.items():
        seg_df = rfm[rfm["segment_id"] == sid]
        segment_summary.append({
            "id": sid,
            "name": info["name"],
            "color": info["color"],
            "description": info["description"],
            "count": len(seg_df),
            "avg_recency":  round(seg_df["recency"].mean(),  1) if len(seg_df) > 0 else 0,
            "avg_frequency": round(seg_df["frequency"].mean(), 1) if len(seg_df) > 0 else 0,
            "avg_monetary": round(seg_df["monetary"].mean(),  2) if len(seg_df) > 0 else 0,
        })

    top_customers = rfm.nlargest(20, "monetary")[
        ["customer_id", "recency", "frequency", "monetary", "segment"]
    ].to_dict(orient="records")

    return {
        "segments": segment_summary,
        "top_customers": top_customers,
        "total_customers": len(rfm),
    }
