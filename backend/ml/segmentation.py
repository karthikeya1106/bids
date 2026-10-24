"""
Customer segmentation: RFM scoring + K-Means clustering.

Each customer gets a Recency / Frequency / Monetary profile, K-Means groups
them into up to four behaviour clusters, and the clusters are ranked and
labelled deterministically (Champions, At-Risk, New / Growing, Lost).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

SEGMENT_LABELS = {
    "Champions": {
        "rank": 0,
        "color": "#000000",
        "description": "Bought recently, purchase often and spend the most.",
    },
    "New / Growing": {
        "rank": 1,
        "color": "#374151",
        "description": "Recent buyers with low frequency and clear upside.",
    },
    "At-Risk": {
        "rank": 2,
        "color": "#6b7280",
        "description": "Historically valuable customers who have gone quiet.",
    },
    "Lost": {
        "rank": 3,
        "color": "#9ca3af",
        "description": "Long inactive, low frequency and low spend.",
    },
}


def compute_rfm(orders_df: pd.DataFrame) -> pd.DataFrame:
    """Recency / frequency / monetary metrics per customer."""
    orders_df = orders_df.copy()
    orders_df["order_date"] = pd.to_datetime(orders_df["order_date"])
    snapshot = orders_df["order_date"].max()

    rfm = (
        orders_df.groupby("customer_id")
        .agg(
            recency=("order_date", lambda x: (snapshot - x.max()).days),
            frequency=("order_id", "nunique"),
            monetary=("sales", "sum"),
            quantity=("quantity", "sum"),
            avg_discount=("discount", "mean"),
        )
        .reset_index()
    )
    rfm["monetary"] = rfm["monetary"].round(2)
    rfm["avg_order_value"] = np.where(
        rfm["frequency"] > 0, rfm["monetary"] / rfm["frequency"], 0.0
    ).round(2)

    # Quintile RFM scores (1 = worst, 5 = best) so clustering is not dominated
    # by the raw monetary scale and segment sizes stay meaningful.
    rfm["r_score"] = _quintile_score(-rfm["recency"])
    rfm["f_score"] = _quintile_score(rfm["frequency"])
    rfm["m_score"] = _quintile_score(rfm["monetary"])
    return rfm


def _quintile_score(values: pd.Series) -> pd.Series:
    """Map a numeric series onto 1–5 quintile scores (higher = better)."""
    try:
        ranks = values.rank(method="first")
        scored = pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5])
        return scored.astype(int)
    except (ValueError, IndexError):
        # Too few distinct values to form quintiles.
        return pd.Series(3, index=values.index, dtype=int)


def _assign_labels(centers_scaled: np.ndarray) -> dict[int, str]:
    """Rank clusters by their combined RFM score and map them to business labels."""
    scores = centers_scaled.sum(axis=1)
    ranking = list(np.argsort(scores)[::-1])  # best first

    assignment: dict[int, str] = {int(ranking[0]): "Champions"}
    if len(ranking) == 1:
        return assignment

    assignment[int(ranking[-1])] = "Lost"

    middles = ranking[1:-1]
    if middles:
        # The fresher middle cluster is growing; the staler one is at risk.
        middles = sorted(middles, key=lambda c: centers_scaled[c, 0], reverse=True)
        for idx, cluster in enumerate(middles):
            assignment[int(cluster)] = "New / Growing" if idx == 0 else "At-Risk"

    return assignment


def run_segmentation(
    orders_df: pd.DataFrame,
    customers_df: pd.DataFrame | None = None,
    top_n: int = 15,
) -> dict:
    """
    Segment customers and return per-segment metrics plus the top customers.

    ``customers_df`` optionally supplies names / account segment / region.
    """
    if orders_df.empty or "customer_id" not in orders_df.columns:
        return {
            "segments": [],
            "top_customers": [],
            "total_customers": 0,
            "total_revenue": 0.0,
            "averages": {},
        }

    rfm = compute_rfm(orders_df)

    features = np.column_stack(
        [
            rfm["r_score"].astype(float),
            rfm["f_score"].astype(float),
            rfm["m_score"].astype(float),
        ]
    )
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    n_clusters = int(min(4, max(1, len(rfm))))
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    rfm["cluster"] = kmeans.fit_predict(scaled)

    centers_scaled = kmeans.cluster_centers_
    assignment = _assign_labels(centers_scaled)
    rfm["segment"] = rfm["cluster"].map(assignment)

    # Attach customer attributes.
    if customers_df is not None and not customers_df.empty:
        attrs = customers_df.rename(columns={"segment": "account_segment"})
        keep = [
            c
            for c in ["customer_id", "customer_name", "account_segment", "region", "state"]
            if c in attrs.columns
        ]
        rfm = rfm.merge(attrs[keep], on="customer_id", how="left")
    for column, default in [
        ("customer_name", None),
        ("account_segment", "Unknown"),
        ("region", "Unknown"),
        ("state", "Unknown"),
    ]:
        if column not in rfm.columns:
            rfm[column] = default

    total_revenue = float(rfm["monetary"].sum())

    # Category / region affinity per customer (revenue-weighted).
    affinity = orders_df.groupby(["customer_id", "category"])["sales"].sum().reset_index()
    top_category = (
        affinity.sort_values("sales", ascending=False)
        .drop_duplicates("customer_id")
        .set_index("customer_id")["category"]
    )
    rfm["top_category"] = rfm["customer_id"].map(top_category).fillna("Uncategorised")

    segments = []
    for name in sorted(assignment.values(), key=lambda n: SEGMENT_LABELS[n]["rank"]):
        group = rfm[rfm["segment"] == name]
        if group.empty:
            continue
        meta = SEGMENT_LABELS[name]
        revenue = float(group["monetary"].sum())
        segments.append(
            {
                "name": name,
                "color": meta["color"],
                "description": meta["description"],
                "count": int(len(group)),
                "share": round(len(group) / len(rfm) * 100, 1),
                "revenue": round(revenue, 2),
                "revenue_share": round(revenue / total_revenue * 100, 1) if total_revenue else 0.0,
                "avg_monetary": round(float(group["monetary"].mean()), 2),
                "avg_frequency": round(float(group["frequency"].mean()), 2),
                "avg_recency": round(float(group["recency"].mean()), 1),
                "avg_order_value": round(float(group["avg_order_value"].mean()), 2),
                "avg_quantity": round(float(group["quantity"].mean()), 1),
                "avg_discount": round(float(group["avg_discount"].mean()) * 100, 1),
                "inactive_share": round(float((group["recency"] > 180).mean() * 100), 1),
                "top_category": (
                    group["top_category"].mode().iloc[0] if not group["top_category"].mode().empty else "—"
                ),
                "top_region": (
                    group["region"].mode().iloc[0]
                    if not group["region"].mode().empty
                    else "—"
                ),
            }
        )

    top_customers = (
        rfm.sort_values("monetary", ascending=False)
        .head(top_n)[
            [
                "customer_id",
                "customer_name",
                "account_segment",
                "region",
                "segment",
                "recency",
                "frequency",
                "monetary",
                "avg_order_value",
                "top_category",
            ]
        ]
        .to_dict(orient="records")
    )

    return {
        "segments": segments,
        "top_customers": top_customers,
        "total_customers": int(len(rfm)),
        "total_revenue": round(total_revenue, 2),
        "averages": {
            "recency": round(float(rfm["recency"].mean()), 1),
            "frequency": round(float(rfm["frequency"].mean()), 2),
            "monetary": round(float(rfm["monetary"].mean()), 2),
            "order_value": round(float(rfm["avg_order_value"].mean()), 2),
        },
    }
