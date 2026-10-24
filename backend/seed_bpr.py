"""
Business Process Rule templates.

Rules are provisioned per workspace (never globally) when a user loads data.
The template carries the logic only; effectiveness and trigger history are
measured from that workspace's own orders at read time.

Usage:
    cd psone/backend
    python seed_bpr.py --owner you@example.com
"""
import argparse
import sys
import os
import io

# Fix Windows console encoding for Unicode output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure the backend package is on the path
sys.path.insert(0, os.path.dirname(__file__))

from db.database import SessionLocal, engine, Base
from db.models import BPRRule  # noqa — registers the model with Base
import db.models  # noqa — ensure all models are registered before create_all
from datetime import datetime

RULES = [
    {
        "rule_name": "High Discount Alert",
        "rule_description": "Flags any order where the applied discount exceeds 30%, indicating a potential margin erosion risk that requires manager approval before processing.",
        "condition_expression": "IF discount_pct > 0.30 AND category IN ('Technology', 'Furniture')",
        "action": "THEN flag order for manager review AND send Slack alert to sales-ops channel",
        "status": "active",
        "effectiveness_score": 0.82,
        "category": "Pricing",
        "last_triggered": datetime(2024, 11, 14, 10, 30),
    },
    {
        "rule_name": "Low Margin Threshold",
        "rule_description": "Detects products or orders where the gross profit margin falls below 5%, triggering a pricing review to prevent loss-making sales.",
        "condition_expression": "IF profit_margin < 0.05 AND quantity > 5",
        "action": "THEN escalate to pricing team AND suppress auto-reorder for this SKU",
        "status": "needs_review",
        "effectiveness_score": 0.51,
        "category": "Profitability",
        "last_triggered": datetime(2024, 10, 28, 15, 0),
    },
    {
        "rule_name": "Stockout Prevention",
        "rule_description": "Monitors projected inventory levels for fast-moving SKUs and triggers a purchase order when days-of-supply falls below 7 days, ensuring continuous availability.",
        "condition_expression": "IF projected_days_of_supply < 7 AND sales_velocity_rank <= 20",
        "action": "THEN create PO for 30-day supply AND notify warehouse manager",
        "status": "active",
        "effectiveness_score": 0.91,
        "category": "Inventory",
        "last_triggered": datetime(2024, 11, 20, 9, 0),
    },
    {
        "rule_name": "Customer Churn Warning",
        "rule_description": "Identifies high-value customers (CLV > $5,000) whose 90-day purchase activity has dropped by more than 20% compared to their baseline, triggering retention measures.",
        "condition_expression": "IF customer_lifetime_value > 5000 AND purchase_drop_90d > 0.20",
        "action": "THEN activate 15% loyalty retention offer AND assign to account manager",
        "status": "active",
        "effectiveness_score": 0.74,
        "category": "Retention",
        "last_triggered": datetime(2024, 11, 5, 11, 0),
    },
    {
        "rule_name": "Seasonal Demand Spike",
        "rule_description": "Detects when the seasonal demand index for a product category exceeds 1.4x the baseline (Q3/Q4 peaks), automatically increasing stock targets by 40%.",
        "condition_expression": "IF seasonal_demand_index > 1.40 AND month IN (10, 11, 12)",
        "action": "THEN increase stock target by 40% AND pre-authorize expedited shipping budget",
        "status": "active",
        "effectiveness_score": 0.88,
        "category": "Demand Planning",
        "last_triggered": datetime(2024, 11, 1, 8, 0),
    },
    {
        "rule_name": "Obsolete Product Archive",
        "rule_description": "Identifies SKUs that have recorded zero customer orders over the past 90 days. These products are archived from the active catalog to reduce warehouse overhead and listing costs.",
        "condition_expression": "IF orders_last_90_days = 0 AND product_age_days > 180",
        "action": "THEN move product to archived status AND remove from active storefront listings",
        "status": "obsolete",
        "effectiveness_score": 0.22,
        "category": "Catalog Management",
        "last_triggered": datetime(2024, 8, 15, 16, 0),
    },
]


def ensure_bpr_rules(db, owner_id: str) -> int:
    """Create this workspace's rule set if it does not exist yet."""
    existing = db.query(BPRRule).filter(BPRRule.owner_id == owner_id).count()
    if existing:
        return existing

    db.add_all(
        [
            BPRRule(
                owner_id=owner_id,
                rule_name=rule["rule_name"],
                rule_description=rule["rule_description"],
                condition_expression=rule["condition_expression"],
                action=rule["action"],
                status="active",
                effectiveness_score=None,
                last_triggered=None,
                category=rule["category"],
            )
            for rule in RULES
        ]
    )
    db.commit()
    return db.query(BPRRule).filter(BPRRule.owner_id == owner_id).count()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Provision BPR rules for one workspace.")
    parser.add_argument("--owner", required=True, help="Account email that owns the rules")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        total = ensure_bpr_rules(db, args.owner.strip().lower())
        print(f"[OK] {total} BPR rules available for {args.owner.strip().lower()}.")
    finally:
        db.close()
