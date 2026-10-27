from sqlalchemy import Column, String, Integer, Float, Date, DateTime, Text, JSON, Index, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from db.database import Base

# Postgres stores each record as real JSONB (compact, indexable); SQLite keeps
# the portable TEXT-backed JSON it has always used.
RecordJSON = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    """A local account. The email is the canonical owner key for all data."""
    __tablename__ = "users"

    email         = Column(String, primary_key=True)
    name          = Column(String)
    password_hash = Column(String)
    created_at    = Column(DateTime, default=func.now())


class Customer(Base):
    __tablename__ = "customers"

    # A customer id is only unique inside one workspace, so the owner is part of
    # the primary key. Two tenants can both have "CUST-1" without colliding.
    owner_id      = Column(String, primary_key=True)
    customer_id   = Column(String, primary_key=True)
    customer_name = Column(String)
    segment       = Column(String)   # Consumer / Corporate / Home Office
    region        = Column(String)
    city          = Column(String)
    state         = Column(String)
    country       = Column(String)


class Order(Base):
    __tablename__ = "orders"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    owner_id     = Column(String, index=True, nullable=False)
    order_id     = Column(String, index=True)
    order_date   = Column(Date)
    ship_date    = Column(Date)
    customer_id  = Column(String, index=True)
    category     = Column(String)
    sub_category = Column(String)
    product_name = Column(String)
    sales        = Column(Float)
    quantity     = Column(Integer)
    discount     = Column(Float)
    profit       = Column(Float)


class KPI(Base):
    __tablename__ = "kpis"
    __table_args__ = (UniqueConstraint("owner_id", "kpi_name", name="uq_kpi_owner_name"),)

    id             = Column(Integer, primary_key=True, autoincrement=True)
    owner_id       = Column(String, index=True, nullable=False)
    kpi_name       = Column(String)
    current_value  = Column(Float)
    baseline_value = Column(Float)
    target_value   = Column(Float)
    drift_score    = Column(Float, default=0.0)
    unit           = Column(String)
    last_updated   = Column(DateTime, default=func.now())


class BPRRule(Base):
    __tablename__ = "bpr_rules"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    owner_id             = Column(String, index=True, nullable=False)
    rule_name            = Column(String)
    rule_description     = Column(Text)
    condition_expression = Column(Text)
    action               = Column(Text)
    status               = Column(String, default="active")   # active / needs_review / obsolete
    effectiveness_score  = Column(Float, default=1.0)
    last_triggered       = Column(DateTime)
    category             = Column(String)


class DatasetMeta(Base):
    """Registry of datasets a workspace has uploaded.

    One row per upload. ``is_active`` marks the dataset the analytics modules
    currently read; older datasets keep their canonical rows in ``dataset_rows``
    and can be re-activated.
    """
    __tablename__ = "dataset_meta"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    owner_id         = Column(String, index=True, nullable=False)
    dataset_name     = Column(String)          # e.g. "Sample - Superstore.csv"
    org_name         = Column(String, nullable=True)   # e.g. "Acme Corp"
    source           = Column(String)          # "upload" | "seed"
    dataset_type     = Column(String, default="sales")  # legacy alias of schema_kind
    schema_kind      = Column(String, default="generic")
    analysis_task    = Column(String, default="eda")
    target_field     = Column(String, nullable=True)
    synthesized      = Column(Integer, default=0)       # 1 if a technical row index was generated
    row_count        = Column(Integer)
    customer_count   = Column(Integer)
    total_sales      = Column(Float)
    is_active        = Column(Integer, default=0)
    materialized     = Column(Integer, default=0)       # 1 when native tables were rebuilt
    profile_json     = Column(Text, nullable=True)
    mapping_json     = Column(Text, nullable=True)
    schema_json      = Column(Text, nullable=True)
    validation_json  = Column(Text, nullable=True)
    capabilities_json = Column(Text, nullable=True)
    uploaded_at      = Column(DateTime, default=func.now())


class DatasetRow(Base):
    """Canonical mapped record for one dataset.

    Keeps every ingested dataset independent of the sales-oriented native
    tables, which lets several datasets coexist and be switched between.
    """
    __tablename__ = "dataset_rows"
    # One covering index serves the only read pattern this table has: every
    # stored record for one dataset, in original order.
    __table_args__ = (
        Index("ix_dataset_rows_owner_dataset_row", "owner_id", "dataset_id", "row_index"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    owner_id   = Column(String, index=True, nullable=False)
    dataset_id = Column(Integer, index=True, nullable=False)
    row_index  = Column(Integer, nullable=False)
    payload    = Column(RecordJSON, nullable=False)


class ChurnSubscriber(Base):
    """One row per subscriber for telecom/churn datasets. Never stored as fake orders."""
    __tablename__ = "churn_subscribers"

    owner_id          = Column(String, primary_key=True)
    subscriber_id     = Column(String, primary_key=True)
    state             = Column(String)
    tenure            = Column(Integer)
    area_code         = Column(String)
    intl_plan         = Column(String)
    voicemail_plan    = Column(String)
    voicemail_msgs    = Column(Integer)
    day_mins          = Column(Float)
    day_calls         = Column(Integer)
    day_charge        = Column(Float)
    eve_mins          = Column(Float)
    eve_calls         = Column(Integer)
    eve_charge        = Column(Float)
    night_mins        = Column(Float)
    night_calls       = Column(Integer)
    night_charge      = Column(Float)
    intl_mins         = Column(Float)
    intl_calls        = Column(Integer)
    intl_charge       = Column(Float)
    service_calls     = Column(Integer)
    churn_status      = Column(String)   # Active / Churned
    total_charge      = Column(Float)
