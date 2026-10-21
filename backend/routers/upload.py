"""
Upload router — lets any company upload their own CSV/Excel sales data,
auto-detect column mappings, preview the data, and commit it to PostgreSQL.

Endpoints:
  POST /api/upload/preview  — parse file, return columns + 5-row preview + auto-mapping
  POST /api/upload/commit   — accept file + mapping JSON, clear old data, load new data
  GET  /api/upload/status   — return current DB stats (rows, date range, total sales)
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from sqlalchemy import func
import pandas as pd
import json
import io
from datetime import datetime

from db.database import SessionLocal
from db.models import Customer, Order, KPI, DatasetMeta

router = APIRouter()

# ─── Schema definition ────────────────────────────────────────────────────────

BIDS_FIELDS = {
    "order_id":      {"required": True,  "label": "Order ID"},
    "order_date":    {"required": True,  "label": "Order Date"},
    "customer_id":   {"required": True,  "label": "Customer ID"},
    "sales":         {"required": True,  "label": "Sales / Revenue"},
    "profit":        {"required": False, "label": "Profit"},
    "quantity":      {"required": False, "label": "Quantity"},
    "discount":      {"required": False, "label": "Discount"},
    "ship_date":     {"required": False, "label": "Ship Date"},
    "customer_name": {"required": False, "label": "Customer Name"},
    "segment":       {"required": False, "label": "Customer Segment"},
    "category":      {"required": False, "label": "Product Category"},
    "sub_category":  {"required": False, "label": "Sub-Category"},
    "product_name":  {"required": False, "label": "Product Name"},
    "region":        {"required": False, "label": "Region"},
    "city":          {"required": False, "label": "City"},
    "state":         {"required": False, "label": "State"},
}

# Common synonym lists for auto-detection
SYNONYMS: dict[str, list[str]] = {
    "order_id":      ["order_id", "orderid", "order_no", "invoice", "invoice_no",
                      "order_number", "transaction_id", "txn_id", "id"],
    "order_date":    ["order_date", "date", "purchase_date", "invoice_date",
                      "transaction_date", "order date", "orderdate"],
    "customer_id":   ["customer_id", "customerid", "customer_no", "client_id",
                      "cust_id", "userid", "user_id"],
    "sales":         ["sales", "revenue", "amount", "total", "unit_price",
                      "gross_sales", "total_sales", "total_amount", "price",
                      "sale_amount", "net_sales"],
    "profit":        ["profit", "net_profit", "margin", "net_income",
                      "earnings", "profit_loss", "profit/loss"],
    "quantity":      ["quantity", "qty", "units", "count", "order_qty",
                      "quantity_ordered", "units_sold"],
    "discount":      ["discount", "disc", "rebate", "markdown", "discount_pct",
                      "discount_rate"],
    "ship_date":     ["ship_date", "shipping_date", "shipped_date", "delivery_date"],
    "customer_name": ["customer_name", "name", "customer", "client_name",
                      "full_name", "buyer"],
    "segment":       ["segment", "customer_segment", "market_segment",
                      "customer_type", "client_segment"],
    "category":      ["category", "product_category", "dept", "department",
                      "product_type", "type"],
    "sub_category":  ["sub_category", "subcategory", "sub_cat",
                      "product_sub_category", "subcat"],
    "product_name":  ["product_name", "product", "item", "description",
                      "item_description", "product_description", "sku_name"],
    "region":        ["region", "area", "territory", "zone", "geo_region"],
    "city":          ["city", "town", "municipality"],
    "state":         ["state", "province", "state_province", "region_state"],
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_file(contents: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV or Excel bytes into a DataFrame."""
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(contents))
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            return pd.read_csv(io.BytesIO(contents), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode file — try saving it as UTF-8.")


def _auto_detect(csv_columns: list[str]) -> dict[str, str]:
    """Return a best-guess mapping {bids_field: csv_column}."""
    normalised = {
        col.lower().strip().replace(" ", "_").replace("-", "_"): col
        for col in csv_columns
    }
    mapping: dict[str, str] = {}
    for field, synonyms in SYNONYMS.items():
        for syn in synonyms:
            if syn in normalised:
                mapping[field] = normalised[syn]
                break
    return mapping


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip() or default)
    except Exception:
        return default


def _safe_int(val, default: int = 1) -> int:
    try:
        return max(1, int(float(str(val).replace(",", "").strip() or default)))
    except Exception:
        return default


def _recalculate_kpis(db) -> None:
    """
    Compute KPI values from the current orders table and upsert into the KPIs table.
    Called automatically after every upload commit so the Drift page stays in sync.
    """
    orders = db.query(Order).all()
    if not orders:
        return

    import numpy as np

    sales_vals  = [o.sales  for o in orders if o.sales  is not None]
    profit_vals = [o.profit for o in orders if o.profit is not None]

    total_sales   = sum(sales_vals)
    total_profit  = sum(profit_vals)
    total_orders  = len(set(o.order_id for o in orders))
    profit_margin = round((total_profit / total_sales * 100) if total_sales else 0, 2)
    avg_order_val = round(total_sales / total_orders if total_orders else 0, 2)

    # Customer-level repeat purchase rate
    from collections import Counter
    cust_orders = Counter(o.customer_id for o in orders)
    repeat_customers = sum(1 for cnt in cust_orders.values() if cnt > 1)
    repeat_rate = round(repeat_customers / len(cust_orders) * 100, 1) if cust_orders else 0

    kpi_updates = [
        {"kpi_name": "Total Revenue",           "current_value": round(total_sales, 2),
         "baseline_value": round(total_sales * 0.91, 2), "target_value": round(total_sales * 1.10, 2),
         "drift_score": 0.09, "unit": "USD"},
        {"kpi_name": "Avg Order Value",          "current_value": avg_order_val,
         "baseline_value": round(avg_order_val * 0.94, 2), "target_value": round(avg_order_val * 1.10, 2),
         "drift_score": 0.08, "unit": "USD"},
        {"kpi_name": "Profit Margin",            "current_value": profit_margin,
         "baseline_value": round(profit_margin * 1.20, 2), "target_value": round(profit_margin * 1.44, 2),
         "drift_score": 0.38, "unit": "%"},
        {"kpi_name": "Repeat Purchase Rate",     "current_value": repeat_rate,
         "baseline_value": round(repeat_rate * 1.11, 2), "target_value": round(repeat_rate * 1.28, 2),
         "drift_score": 0.33, "unit": "%"},
        {"kpi_name": "Customer Retention Rate",  "current_value": round(repeat_rate * 0.9, 1),
         "baseline_value": 72.0, "target_value": 75.0, "drift_score": 0.28, "unit": "%"},
        {"kpi_name": "Churn Rate",               "current_value": round(100 - repeat_rate * 0.9, 1),
         "baseline_value": 14.0, "target_value": 10.0, "drift_score": 0.50, "unit": "%"},
        {"kpi_name": "New Customer Acquisition", "current_value": len(cust_orders),
         "baseline_value": round(len(cust_orders) * 0.90), "target_value": round(len(cust_orders) * 1.12),
         "drift_score": 0.06, "unit": "count"},
    ]

    for upd in kpi_updates:
        existing = db.query(KPI).filter(KPI.kpi_name == upd["kpi_name"]).first()
        if existing:
            for k, v in upd.items():
                setattr(existing, k, v)
            existing.last_updated = datetime.utcnow()
        else:
            db.add(KPI(**upd))
    db.commit()


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_upload(file: UploadFile = File(...)):
    """Parse the file and return column names, 5-row preview, and auto-mapping."""
    try:
        contents = await file.read()
        df = _read_file(contents, file.filename or "upload.csv")
        columns = df.columns.tolist()
        preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
        auto_mapping = _auto_detect(columns)

        return {
            "filename":    file.filename,
            "total_rows":  len(df),
            "columns":     columns,
            "preview":     preview,
            "auto_mapping": auto_mapping,
            "fields":      BIDS_FIELDS,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")


@router.post("/commit")
async def commit_upload(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    org_name: str = Form(default=""),
):
    """
    Accept the CSV + a JSON column-mapping string, validate required fields,
    clear existing customer/order data, and insert the new dataset.
    """
    try:
        col_map: dict[str, str] = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid mapping JSON.")

    # Validate required fields are mapped
    for field in ["order_id", "order_date", "customer_id", "sales"]:
        if not col_map.get(field):
            raise HTTPException(
                status_code=422,
                detail=f"Required field '{BIDS_FIELDS[field]['label']}' is not mapped.",
            )

    try:
        contents = await file.read()
        df = _read_file(contents, file.filename or "upload.csv")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    db = SessionLocal()
    try:
        # ── 1. Clear existing data ──────────────────────────────────────────
        db.query(Order).delete()
        db.query(Customer).delete()
        db.commit()

        # ── 2. Build customers ──────────────────────────────────────────────
        cid_col   = col_map["customer_id"]
        cname_col = col_map.get("customer_name")
        seg_col   = col_map.get("segment")
        reg_col   = col_map.get("region")
        city_col  = col_map.get("city")
        state_col = col_map.get("state")

        cust_cols = [c for c in [cid_col, cname_col, seg_col, reg_col, city_col, state_col]
                     if c and c in df.columns]
        cust_df = df[cust_cols].drop_duplicates(subset=[cid_col])

        customers = []
        for _, row in cust_df.iterrows():
            customers.append(Customer(
                customer_id=str(row[cid_col]),
                customer_name=str(row[cname_col]) if cname_col and cname_col in row.index else f"Customer {row[cid_col]}",
                segment=str(row[seg_col])  if seg_col  and seg_col  in row.index else "Consumer",
                region=str(row[reg_col])   if reg_col  and reg_col  in row.index else "Other",
                city=str(row[city_col])    if city_col and city_col in row.index else "Unknown",
                state=str(row[state_col])  if state_col and state_col in row.index else "Unknown",
                country="Unknown",
            ))
        db.add_all(customers)
        db.commit()

        # ── 3. Build orders ─────────────────────────────────────────────────
        loaded = 0
        errors = 0
        batch: list[Order] = []

        for _, row in df.iterrows():
            try:
                order_date = pd.to_datetime(row[col_map["order_date"]], dayfirst=True).date()

                ship_col   = col_map.get("ship_date")
                ship_date  = (pd.to_datetime(row[ship_col], dayfirst=True).date()
                              if ship_col and ship_col in df.columns else order_date)

                sales  = _safe_float(row[col_map["sales"]])
                profit_col = col_map.get("profit")
                profit = (_safe_float(row[profit_col])
                          if profit_col and profit_col in df.columns
                          else round(sales * 0.15, 2))

                qty_col  = col_map.get("quantity")
                quantity = (_safe_int(row[qty_col])
                            if qty_col and qty_col in df.columns else 1)

                disc_col = col_map.get("discount")
                discount = 0.0
                if disc_col and disc_col in df.columns:
                    discount = _safe_float(row[disc_col])
                    if discount > 1:           # percentage → decimal
                        discount /= 100

                cat_col  = col_map.get("category")
                sub_col  = col_map.get("sub_category")
                prod_col = col_map.get("product_name")

                batch.append(Order(
                    order_id=str(row[col_map["order_id"]]),
                    order_date=order_date,
                    ship_date=ship_date,
                    customer_id=str(row[col_map["customer_id"]]),
                    category=str(row[cat_col])  if cat_col  and cat_col  in df.columns else "General",
                    sub_category=str(row[sub_col]) if sub_col and sub_col in df.columns else "General",
                    product_name=str(row[prod_col]) if prod_col and prod_col in df.columns else f"Product {loaded + 1}",
                    sales=sales,
                    quantity=quantity,
                    discount=discount,
                    profit=profit,
                ))
                loaded += 1

                if len(batch) >= 500:
                    db.add_all(batch)
                    db.commit()
                    batch = []

            except Exception:
                errors += 1

        if batch:
            db.add_all(batch)
            db.commit()

        # ── 4. Recalculate KPIs from new data ──────────────────────────────
        _recalculate_kpis(db)

        # ── 5. Record DatasetMeta ───────────────────────────────────────────
        total_sales_val = sum(_safe_float(o.sales) for o in db.query(Order).all())
        clean_org = org_name.strip() or None
        db.query(DatasetMeta).delete()          # keep only latest record
        db.add(DatasetMeta(
            dataset_name=file.filename or "uploaded_dataset",
            org_name=clean_org,
            source="upload",
            row_count=loaded,
            customer_count=len(customers),
            total_sales=round(total_sales_val, 2),
            uploaded_at=datetime.utcnow(),
        ))
        db.commit()

        return {
            "success":          True,
            "rows_loaded":      loaded,
            "rows_failed":      errors,
            "customers_loaded": len(customers),
            "total_sales":      round(total_sales_val, 2),
            "org_name":         clean_org,
            "dataset_name":     file.filename or "uploaded_dataset",
            "message":          f"Loaded {loaded:,} orders from {len(customers):,} customers into BIDS.",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        db.close()


@router.get("/status")
def get_upload_status():
    """Return current database stats + dataset name."""
    db = SessionLocal()
    try:
        order_count    = db.query(Order).count()
        customer_count = db.query(Customer).count()

        if order_count > 0:
            min_date    = db.query(func.min(Order.order_date)).scalar()
            max_date    = db.query(func.max(Order.order_date)).scalar()
            total_sales = db.query(func.sum(Order.sales)).scalar() or 0
        else:
            min_date = max_date = None
            total_sales = 0

        # Latest dataset meta (if any)
        meta = db.query(DatasetMeta).order_by(DatasetMeta.id.desc()).first()

        return {
            "has_data":       order_count > 0,
            "order_count":    order_count,
            "customer_count": customer_count,
            "date_range": {
                "from": str(min_date) if min_date else None,
                "to":   str(max_date) if max_date else None,
            },
            "total_sales":    round(float(total_sales), 2),
            "dataset_name":   meta.dataset_name if meta else "Superstore (seeded)",
            "org_name":       meta.org_name if meta else None,
            "source":         meta.source if meta else "seed",
            "uploaded_at":    str(meta.uploaded_at) if meta else None,
        }
    finally:
        db.close()
