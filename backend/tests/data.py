"""Deterministic representative datasets for the pipeline tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(11)


def sales_standard(rows: int = 180) -> pd.DataFrame:
    start = pd.Timestamp("2023-01-01")
    records = []
    for i in range(rows):
        day = start + pd.Timedelta(days=int(i * 5))
        units = int(RNG.integers(1, 8))
        price = round(float(RNG.uniform(40, 500)), 2)
        records.append({
            "Order ID": f"CA-2023-{100000 + i}",
            "Order Date": day.strftime("%Y-%m-%d"),
            "Customer ID": f"CUST-{i % 45:03d}",
            "Customer Name": f"Customer {i % 45}",
            "Segment": ["Consumer", "Corporate", "Home Office"][i % 3],
            "Category": ["Furniture", "Technology", "Office Supplies"][i % 3],
            "Sub-Category": ["Chairs", "Phones", "Paper"][i % 3],
            "Product Name": ["Chair", "Phone", "Paper ream"][i % 3],
            "Region": ["West", "East", "Central"][i % 3],
            "City": ["Seattle", "New York", "Chicago"][i % 3],
            "State": ["WA", "NY", "IL"][i % 3],
            "Sales": round(price * units, 2),
            "Profit": round(price * units * 0.18 - 12, 2),
            "Quantity": units,
            "Discount": round(float(RNG.uniform(0, 0.3)), 3),
        })
    return pd.DataFrame(records)


def sales_with_elastic_demand(rows: int = 400) -> pd.DataFrame:
    """Orders whose quantity genuinely responds to unit price.

    Unit price is drawn log-uniformly and quantity is proportional to
    ``price ** -1.6`` with multiplicative noise, so the simulator can be shown to
    *measure* elasticity from the data instead of falling back to its prior. The
    price range keeps quantity above the integer floor, which would otherwise
    flatten the response at the expensive end.
    """
    rng = np.random.default_rng(23)
    start = pd.Timestamp("2022-01-01")
    records = []
    for i in range(rows):
        day = start + pd.Timedelta(days=int(i * 2))
        price = float(np.round(np.exp(rng.uniform(np.log(6), np.log(45))), 2))
        units = max(1, int(round((price ** -1.6) * 900 * float(rng.uniform(0.85, 1.15)))))
        sales = round(price * units, 2)
        records.append({
            "Order ID": f"EL-{100000 + i}",
            "Order Date": day.strftime("%Y-%m-%d"),
            "Customer ID": f"CUST-{i % 60:03d}",
            "Customer Name": f"Customer {i % 60}",
            "Category": ["Furniture", "Technology", "Office Supplies"][i % 3],
            "Sub-Category": ["Chairs", "Phones", "Paper"][i % 3],
            "Product Name": ["Chair", "Phone", "Paper ream"][i % 3],
            "Region": ["West", "East", "Central"][i % 3],
            "Sales": sales,
            "Quantity": units,
            "Discount": round(float(rng.uniform(0, 0.2)), 3),
            "Profit": round(sales * 0.35 - 4, 2),
        })
    return pd.DataFrame(records)


def sales_alt_names(rows: int = 120) -> pd.DataFrame:
    start = pd.Timestamp("2022-06-01")
    return pd.DataFrame({
        "txn_id": [f"TXN{i:05d}" for i in range(rows)],
        "purchase_date": [(start + pd.Timedelta(days=i * 7)).strftime("%d/%m/%Y") for i in range(rows)],
        "client_id": [f"C{i % 30}" for i in range(rows)],
        "Sales_Amount": [round(float(RNG.uniform(20, 400)), 2) for _ in range(rows)],
        "Units": [int(RNG.integers(1, 5)) for _ in range(rows)],
        "Product_Category": [["Garden", "Tools", "Paint"][i % 3] for i in range(rows)],
        "Region": [["North", "South"][i % 2] for i in range(rows)],
    })


def telecom_churn(rows: int = 200) -> pd.DataFrame:
    states = ["KS", "OH", "NJ", "CA", "TX"]
    records = []
    for i in range(rows):
        day = float(RNG.uniform(60, 320))
        eve = float(RNG.uniform(50, 350))
        night = float(RNG.uniform(80, 400))
        intl = float(RNG.uniform(1, 20))
        service_calls = int(RNG.integers(0, 9))
        churn = "Yes" if (service_calls >= 4 and i % 3 == 0) else "No"
        records.append({
            "State": states[i % len(states)],
            "Account length": int(RNG.integers(1, 240)),
            "Area code": int(RNG.choice([408, 415, 510])),
            "International plan": "Yes" if i % 7 == 0 else "No",
            "Voice mail plan": "Yes" if i % 5 == 0 else "No",
            "Number vmail messages": int(RNG.integers(0, 45)),
            "Total day minutes": round(day, 2),
            "Total day calls": int(RNG.integers(40, 165)),
            "Total day charge": round(day * 0.17, 2),
            "Total eve minutes": round(eve, 2),
            "Total eve calls": int(RNG.integers(40, 170)),
            "Total eve charge": round(eve * 0.085, 2),
            "Total night minutes": round(night, 2),
            "Total night calls": int(RNG.integers(40, 175)),
            "Total night charge": round(night * 0.045, 2),
            "Total intl minutes": round(intl, 2),
            "Total intl calls": int(RNG.integers(1, 15)),
            "Total intl charge": round(intl * 0.27, 2),
            "Customer service calls": service_calls,
            "Churn": churn,
        })
    return pd.DataFrame(records)


def subscription_churn(rows: int = 600, shifted: bool = False) -> pd.DataFrame:
    """Mirrors the columns of the internet-service churn export.

    ``shifted`` lowers usage and raises failures to produce a genuinely
    different distribution for the drift comparison test.
    """
    rng = np.random.default_rng(7 if not shifted else 19)
    records = []
    for i in range(rows):
        failures = int(rng.integers(0, 6)) + (2 if shifted else 0)
        download = None if i % 17 == 0 else round(float(rng.uniform(0, 90)) * (0.55 if shifted else 1), 2)
        upload = None if i % 17 == 0 else round(float(rng.uniform(0, 10)) * (0.7 if shifted else 1), 2)
        remaining = None if i % 5 == 0 else round(float(rng.uniform(0, 3)), 2)
        risk = 0.18
        if remaining is not None and remaining < 0.6:
            risk += 0.35
        if failures >= 3:
            risk += 0.18
        if download is not None and download < 10:
            risk += 0.15
        if shifted:
            risk += 0.12
        records.append({
            "id": 1000 + i,
            "is_tv_subscriber": 1 if i % 3 else 0,
            "is_movie_package_subscriber": 1 if i % 4 == 0 else 0,
            "subscription_age": round(float(rng.uniform(1, 40)), 2),
            "bill_avg": round(float(rng.uniform(0, 60)), 2),
            "reamining_contract": remaining,
            "service_failure_count": failures,
            "download_avg": download,
            "upload_avg": upload,
            "download_over_limit": int(rng.integers(0, 4)),
            "churn": 1 if rng.random() < min(0.95, risk) else 0,
        })
    return pd.DataFrame(records)


def iris_like(rows: int = 150) -> pd.DataFrame:
    species = ["setosa", "versicolor", "virginica"]
    labels = [species[i % 3] for i in range(rows)]
    return pd.DataFrame({
        "sepal_length": np.round(RNG.normal(5.8, 0.7, rows), 2),
        "sepal_width": np.round(RNG.normal(3.0, 0.4, rows), 2),
        "petal_length": np.round([RNG.normal(1.5 if s == "setosa" else 4.5, 0.6) for s in labels], 2),
        "petal_width": np.round([RNG.normal(0.3 if s == "setosa" else 1.4, 0.3) for s in labels], 2),
        "species": labels,
    })


def regression_generic(rows: int = 160) -> pd.DataFrame:
    size = RNG.normal(120, 25, rows)
    age = RNG.integers(1, 30, rows)
    price = np.round(size * 12 + age * 3 + RNG.normal(0, 40, rows), 2)
    return pd.DataFrame({
        "property_id": [f"P{i:04d}" for i in range(rows)],
        "size_sqft": np.round(size, 1),
        "building_age": age,
        "neighbourhood": [["North", "South", "East"][i % 3] for i in range(rows)],
        "price": price,
    })


def monthly_timeseries(periods: int = 36) -> pd.DataFrame:
    months = pd.period_range("2021-01", periods=periods, freq="M")
    base = 1000 + np.arange(periods) * 35
    noise = RNG.normal(0, 80, periods)
    return pd.DataFrame({
        "month": [month.strftime("%Y-%m-%d") for month in months],
        "revenue": np.round(base + noise, 2),
        "channel": [["online", "store"][i % 2] for i in range(periods)],
    })


def categorical_only(rows: int = 80) -> pd.DataFrame:
    return pd.DataFrame({
        "region": [["North", "South", "East", "West"][i % 4] for i in range(rows)],
        "product": [["A", "B", "C"][i % 3] for i in range(rows)],
        "tier": [["Basic", "Pro"][i % 2] for i in range(rows)],
    })


def sales_missing_required() -> pd.DataFrame:
    frame = sales_standard(60)
    return frame.drop(columns=["Order Date"])


def sales_incompatible_types() -> pd.DataFrame:
    frame = sales_standard(60)
    frame["Sales"] = "not a number"
    return frame


def sales_sparse_timeline(rows: int = 60) -> pd.DataFrame:
    """Real sales rows in two dense clusters with a two-year hole between them.

    The detected frequency stays daily, so the gap shows up as missing periods —
    the case where forecasting is offered but the history cannot support it.
    """
    def day(index: int) -> str:
        if index < rows // 2:
            return f"2022-01-{index + 1:02d}"
        return f"2024-01-{index - rows // 2 + 1:02d}"

    return pd.DataFrame({
        "Order ID": [f"CA-{1000 + i}" for i in range(rows)],
        "Order Date": [day(i) for i in range(rows)],
        "Customer ID": [f"CUST-{i % 12:03d}" for i in range(rows)],
        "Customer Name": [f"Customer {i % 12}" for i in range(rows)],
        "Category": [["Furniture", "Technology"][i % 2] for i in range(rows)],
        "Region": [["East", "West"][i % 2] for i in range(rows)],
        "Sales": [round(80 + (i * 23) % 500, 2) for i in range(rows)],
        "Quantity": [1 + i % 4 for i in range(rows)],
        "Profit": [round((80 + (i * 23) % 500) * 0.15 - 10, 2) for i in range(rows)],
    })


def sales_with_duplicates_and_gaps() -> pd.DataFrame:
    frame = sales_standard(80)
    frame.loc[frame.index[:10], "Customer ID"] = None
    duplicated = frame.head(10)
    return pd.concat([frame, duplicated], ignore_index=True)
