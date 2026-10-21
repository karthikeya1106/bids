from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()

from routers import dashboard, behavior, segmentation, rootcause, drift, forecast, strategy, upload, analysis
from db.database import engine, Base

Base.metadata.create_all(bind=engine)

# ── Run lightweight migrations for new columns ─────────────────────────────
from sqlalchemy import text
from db.database import SessionLocal as _SL
def _run_migrations():
    db = _SL()
    try:
        from sqlalchemy import inspect
        insp = inspect(engine)
        if "dataset_meta" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("dataset_meta")]
            if "org_name" not in cols:
                db.execute(text("ALTER TABLE dataset_meta ADD COLUMN org_name VARCHAR;"))
                db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
_run_migrations()

app = FastAPI(
    title="BIDS API",
    description="Business Intelligence Decision System — Backend API",
    version="1.0.0",
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(behavior.router, prefix="/api/behavior", tags=["Behavior Analytics"])
app.include_router(segmentation.router, prefix="/api/segments", tags=["Segmentation"])
app.include_router(rootcause.router, prefix="/api/rootcause", tags=["Root Cause Analysis"])
app.include_router(drift.router, prefix="/api/drift", tags=["Data Drift & BPR"])
app.include_router(forecast.router, prefix="/api/forecast", tags=["Forecasting"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["Strategy AI"])
app.include_router(upload.router,   prefix="/api/upload",   tags=["Data Upload"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis Report"])


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "system": "BIDS API v1.0"}
