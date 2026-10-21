"""
Seed script: loads Kaggle Superstore dataset CSV into PostgreSQL.
Place the 'Sample - Superstore.csv' file in backend/data/ before running.
Run: python -m db.seed
"""
import pandas as pd
import sys
import os
from datetime import datetime, date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, SessionLocal, Base
from db.models import Customer, Order, KPI, BPRRule


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "Sample - Superstore.csv")
    if not os.path.exists(csv_path):
        print("[INFO] Superstore CSV not found. Seeding mock data instead...")
        seed_mock_data(db)
        db.close()
        seed_kpis_and_rules()
        return

    try:
        df = pd.read_csv(csv_path, encoding="latin-1")
        df.columns = [c.strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]

        # --- Customers ---
        db.query(Customer).delete()
        customers = df[["customer_id", "customer_name", "segment", "region", "city", "state", "country"]].drop_duplicates("customer_id")
        for _, row in customers.iterrows():
            db.add(Customer(
                customer_id=row["customer_id"],
                customer_name=row["customer_name"],
                segment=row["segment"],
                region=row["region"],
                city=row["city"],
                state=row.get("state", ""),
                country=row.get("country", "United States"),
            ))

        # --- Orders ---
        db.query(Order).delete()
        for _, row in df.iterrows():
            db.add(Order(
                order_id=row["order_id"],
                order_date=pd.to_datetime(row["order_date"]).date(),
                ship_date=pd.to_datetime(row["ship_date"]).date(),
                customer_id=row["customer_id"],
                category=row["category"],
                sub_category=row["sub_category"],
                product_name=row["product_name"],
                sales=float(row["sales"]),
                quantity=int(row["quantity"]),
                discount=float(row["discount"]),
                profit=float(row["profit"]),
            ))

        db.commit()
        print(f"[OK] Seeded {len(customers)} customers and {len(df)} orders from CSV")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error seeding from CSV: {e}")
        print("Falling back to mock data...")
        seed_mock_data(db)
    finally:
        db.close()
        seed_kpis_and_rules()


def seed_mock_data(db):
    """Generate synthetic Superstore-like data if CSV is missing."""
    import random
    from datetime import timedelta

    categories = [
        ("Furniture", ["Chairs", "Tables", "Bookcases", "Furnishings"]),
        ("Technology", ["Phones", "Accessories", "Machines", "Copiers"]),
        ("Office Supplies", ["Binders", "Paper", "Storage", "Labels"]),
    ]
    regions = ["West", "East", "Central", "South"]
    segments = ["Consumer", "Corporate", "Home Office"]
    states = ["California", "New York", "Texas", "Florida", "Illinois", "Washington", "Ohio"]

    db.query(Customer).delete()
    db.query(Order).delete()

    base_date = date(2021, 1, 1)
    all_customers = []
    for i in range(800):
        cid = f"CUST-{1000+i}"
        all_customers.append(Customer(
            customer_id=cid,
            customer_name=f"Customer {i+1}",
            segment=random.choice(segments),
            region=random.choice(regions),
            city="Springfield",
            state=random.choice(states),
            country="United States",
        ))
    db.add_all(all_customers)

    for i in range(9000):
        days_offset = random.randint(0, 1460)
        order_date = base_date + timedelta(days=days_offset)
        cat, subs = random.choice(categories)
        sub = random.choice(subs)
        qty = random.randint(1, 10)
        base_price = random.uniform(10, 1200)
        discount = random.choice([0, 0.1, 0.2, 0.3, 0.4])
        sales = round(base_price * qty * (1 - discount), 2)
        profit = round(sales * random.uniform(-0.3, 0.45), 2)

        db.add(Order(
            order_id=f"ORD-{2021+days_offset//365}-{10000+i}",
            order_date=order_date,
            ship_date=order_date + timedelta(days=random.randint(2, 7)),
            customer_id=all_customers[random.randint(0, 799)].customer_id,
            category=cat,
            sub_category=sub,
            product_name=f"{sub} Product {random.randint(1,50)}",
            sales=sales,
            quantity=qty,
            discount=discount,
            profit=profit,
        ))

    db.commit()
    print("[OK] Mock data seeded: 800 customers, 9000 orders")


def seed_kpis_and_rules():
    db = SessionLocal()
    try:
        # KPIs
        db.query(KPI).delete()
        kpis = [
            KPI(kpi_name="Total Revenue", current_value=2297201, baseline_value=2100000, target_value=2500000, drift_score=0.12, unit="USD"),
            KPI(kpi_name="Avg Order Value", current_value=458, baseline_value=430, target_value=500, drift_score=0.08, unit="USD"),
            KPI(kpi_name="Customer Retention Rate", current_value=67.4, baseline_value=72.0, target_value=75.0, drift_score=0.31, unit="%"),
            KPI(kpi_name="Profit Margin", current_value=12.5, baseline_value=15.0, target_value=18.0, drift_score=0.42, unit="%"),
            KPI(kpi_name="Churn Rate", current_value=18.2, baseline_value=14.0, target_value=10.0, drift_score=0.55, unit="%"),
            KPI(kpi_name="New Customer Acquisition", current_value=312, baseline_value=280, target_value=350, drift_score=0.06, unit="count"),
            KPI(kpi_name="Repeat Purchase Rate", current_value=43.1, baseline_value=48.0, target_value=55.0, drift_score=0.37, unit="%"),
        ]
        db.add_all(kpis)

        # BPR Rules
        db.query(BPRRule).delete()
        rules = [
            BPRRule(rule_name="Loyalty Discount Trigger", rule_description="Apply 15% discount when customer makes 5+ purchases in a quarter", condition_expression="purchase_count_90d >= 5", action="Apply 15% loyalty discount on next order", status="active", effectiveness_score=0.88, category="Retention"),
            BPRRule(rule_name="High-Value Upsell Prompt", rule_description="Trigger upsell recommendation when cart value exceeds $500", condition_expression="cart_value > 500", action="Show premium product bundle recommendation", status="active", effectiveness_score=0.74, category="Revenue"),
            BPRRule(rule_name="Churn Prevention Alert", rule_description="Flag customer for re-engagement if no purchase in 90 days", condition_expression="days_since_last_purchase >= 90", action="Send personalized re-engagement email campaign", status="needs_review", effectiveness_score=0.51, category="Retention"),
            BPRRule(rule_name="Bulk Order B2B Discount", rule_description="Apply 20% discount on orders with quantity > 20 for Corporate segment", condition_expression="quantity > 20 AND segment == 'Corporate'", action="Apply 20% bulk discount automatically", status="active", effectiveness_score=0.91, category="Pricing"),
            BPRRule(rule_name="Seasonal Markdown Policy", rule_description="Reduce Furniture prices by 25% in Q4 to clear inventory", condition_expression="quarter == 4 AND category == 'Furniture'", action="Apply 25% markdown to all Furniture SKUs", status="needs_review", effectiveness_score=0.43, category="Pricing"),
            BPRRule(rule_name="Low-Margin SKU Freeze", rule_description="Pause promotions on any SKU with profit margin below 5%", condition_expression="profit_margin < 0.05", action="Remove SKU from active campaign lists", status="obsolete", effectiveness_score=0.22, category="Operations"),
            BPRRule(rule_name="Regional Inventory Reorder", rule_description="Trigger restock when regional stock falls below 30 units", condition_expression="regional_stock < 30", action="Auto-generate purchase order for 100 units", status="active", effectiveness_score=0.95, category="Operations"),
        ]
        db.add_all(rules)
        db.commit()
        print("[OK] KPIs and BPR Rules seeded")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
