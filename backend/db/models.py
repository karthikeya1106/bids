from sqlalchemy import Column, String, Integer, Float, Date, DateTime, Text, func
from db.database import Base


class Customer(Base):
    __tablename__ = "customers"

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

    id             = Column(Integer, primary_key=True, autoincrement=True)
    kpi_name       = Column(String, unique=True)
    current_value  = Column(Float)
    baseline_value = Column(Float)
    target_value   = Column(Float)
    drift_score    = Column(Float, default=0.0)
    unit           = Column(String)
    last_updated   = Column(DateTime, default=func.now())


class BPRRule(Base):
    __tablename__ = "bpr_rules"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    rule_name            = Column(String)
    rule_description     = Column(Text)
    condition_expression = Column(Text)
    action               = Column(Text)
    status               = Column(String, default="active")   # active / needs_review / obsolete
    effectiveness_score  = Column(Float, default=1.0)
    last_triggered       = Column(DateTime)
    category             = Column(String)


class DatasetMeta(Base):
    """Tracks which dataset is currently loaded — shown in sidebar & upload page."""
    __tablename__ = "dataset_meta"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    dataset_name = Column(String)          # e.g. "Sample - Superstore.csv"
    org_name     = Column(String, nullable=True)   # e.g. "Acme Corp"
    source       = Column(String)          # "upload" | "seed"
    row_count    = Column(Integer)
    customer_count = Column(Integer)
    total_sales  = Column(Float)
    uploaded_at  = Column(DateTime, default=func.now())
