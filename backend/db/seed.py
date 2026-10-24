"""
Seed one workspace with data.

Loads ``backend/data/Sample - Superstore.csv`` when present, otherwise falls
back to synthetic demo data. Everything is written under the ``--owner`` email,
so seeding never creates data that another account can see.

Run from the backend directory:
    python -m db.seed --owner demo@example.com
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, timedelta

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import Base, SessionLocal, engine
from db.models import Customer, DatasetMeta, Order
from seed_bpr import ensure_bpr_rules
from services.analytics import recalculate_kpis

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BACKEND_DIR, "data", "Sample - Superstore.csv")


def _clear(db, owner_id: str) -> None:
    db.query(Order).filter(Order.owner_id == owner_id).delete()
    db.query(Customer).filter(Customer.owner_id == owner_id).delete()
    db.query(DatasetMeta).filter(DatasetMeta.owner_id == owner_id).delete()
    db.commit()


def _load_superstore(db, owner_id: str) -> dict:
    df = pd.read_csv(CSV_PATH, encoding="latin-1")
    df.columns = [c.strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["ship_date"] = pd.to_datetime(df["ship_date"], errors="coerce")
    df = df.dropna(subset=["order_date", "customer_id", "order_id", "sales"])

    customers = df.drop_duplicates("customer_id")
    db.add_all(
        [
            Customer(
                owner_id=owner_id,
                customer_id=str(row["customer_id"]),
                customer_name=str(row.get("customer_name") or row["customer_id"]),
                segment=str(row.get("segment") or "Unknown"),
                region=str(row.get("region") or "Unknown"),
                city=str(row.get("city") or "Unknown"),
                state=str(row.get("state") or "Unknown"),
                country=str(row.get("country") or "Unknown"),
            )
            for _, row in customers.iterrows()
        ]
    )
    db.commit()

    batch: list[Order] = []
    for _, row in df.iterrows():
        ship_date = row["ship_date"]
        batch.append(
            Order(
                owner_id=owner_id,
                order_id=str(row["order_id"]),
                order_date=row["order_date"].date(),
                ship_date=ship_date.date() if pd.notna(ship_date) else row["order_date"].date(),
                customer_id=str(row["customer_id"]),
                category=str(row.get("category") or "General"),
                sub_category=str(row.get("sub_category") or "General"),
                product_name=str(row.get("product_name") or "Unknown product"),
                sales=float(row["sales"]),
                quantity=int(row.get("quantity") or 1),
                discount=float(row.get("discount") or 0),
                profit=float(row["profit"]) if pd.notna(row.get("profit")) else 0.0,
            )
        )
        if len(batch) >= 1000:
            db.add_all(batch)
            db.commit()
            batch = []
    if batch:
        db.add_all(batch)
        db.commit()

    total_sales = float(df["sales"].sum())
    db.add(
        DatasetMeta(
            owner_id=owner_id,
            dataset_name=os.path.basename(CSV_PATH),
            org_name=None,
            source="seed",
            row_count=int(len(df)),
            customer_count=int(customers["customer_id"].nunique()),
            total_sales=round(total_sales, 2),
        )
    )
    db.commit()

    return {
        "dataset": os.path.basename(CSV_PATH),
        "orders": int(len(df)),
        "customers": int(customers["customer_id"].nunique()),
        "total_sales": round(total_sales, 2),
    }


def _seed_mock(db, owner_id: str) -> dict:
    """Synthetic fallback used only when the CSV is missing."""
    categories = [
        ("Furniture", ["Chairs", "Tables", "Bookcases", "Furnishings"]),
        ("Technology", ["Phones", "Accessories", "Machines", "Copiers"]),
        ("Office Supplies", ["Binders", "Paper", "Storage", "Labels"]),
    ]
    regions = ["West", "East", "Central", "South"]
    segments = ["Consumer", "Corporate", "Home Office"]
    states = ["California", "New York", "Texas", "Florida", "Illinois", "Washington", "Ohio"]

    base_date = date(2021, 1, 1)
    customer_ids = []
    for i in range(800):
        cid = f"CUST-{1000 + i}"
        customer_ids.append(cid)
        db.add(
            Customer(
                owner_id=owner_id,
                customer_id=cid,
                customer_name=f"Customer {i + 1}",
                segment=random.choice(segments),
                region=random.choice(regions),
                city="Springfield",
                state=random.choice(states),
                country="United States",
            )
        )
    db.commit()

    for i in range(9000):
        days_offset = random.randint(0, 1460)
        order_date = base_date + timedelta(days=days_offset)
        cat, subs = random.choice(categories)
        sub = random.choice(subs)
        qty = random.randint(1, 10)
        discount = random.choice([0, 0.1, 0.2, 0.3, 0.4])
        sales = round(random.uniform(10, 1200) * qty * (1 - discount), 2)
        db.add(
            Order(
                owner_id=owner_id,
                order_id=f"ORD-{2021 + days_offset // 365}-{10000 + i}",
                order_date=order_date,
                ship_date=order_date + timedelta(days=random.randint(2, 7)),
                customer_id=random.choice(customer_ids),
                category=cat,
                sub_category=sub,
                product_name=f"{sub} Product {random.randint(1, 50)}",
                sales=sales,
                quantity=qty,
                discount=discount,
                profit=round(sales * random.uniform(-0.3, 0.45), 2),
            )
        )
    db.commit()

    total = sum(row[0] for row in db.query(Order.sales).filter(Order.owner_id == owner_id).all())
    db.add(
        DatasetMeta(
            owner_id=owner_id,
            dataset_name="Synthetic demo dataset",
            org_name=None,
            source="seed",
            row_count=9000,
            customer_count=800,
            total_sales=round(total, 2),
        )
    )
    db.commit()

    return {
        "dataset": "Synthetic demo dataset",
        "orders": 9000,
        "customers": 800,
        "total_sales": round(total, 2),
    }


def seed(owner_id: str) -> None:
    owner_id = owner_id.strip().lower()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _clear(db, owner_id)
        if os.path.exists(CSV_PATH):
            summary = _load_superstore(db, owner_id)
        else:
            print("[INFO] Superstore CSV not found — seeding synthetic data instead.")
            summary = _seed_mock(db, owner_id)

        rules = ensure_bpr_rules(db, owner_id)
        recalculate_kpis(db, owner_id)

        print(
            f"[OK] Seeded {summary['orders']:,} orders for {summary['customers']:,} customers "
            f"({summary['dataset']}) into {owner_id} — ${summary['total_sales']:,.2f} revenue, "
            f"{rules} BPR rules."
        )
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Seeding failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load sample data into one workspace.")
    parser.add_argument("--owner", required=True, help="Account email that will own the data")
    args = parser.parse_args()
    seed(args.owner)
