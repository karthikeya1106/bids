from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

load_dotenv()

from routers import (
    analysis,
    auth,
    behavior,
    dashboard,
    drift,
    forecast,
    rootcause,
    segmentation,
    strategy,
    upload,
)

from db.database import engine, Base
from db.migrate import migrate_legacy_tables
from security import verify_signature

# Drop the old globally shared demo tables before the tenant-scoped schema is
# created. `users` and every data table are rebuilt empty.
migrate_legacy_tables(engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="BIDS API",
    description="Business Intelligence Decision System — Backend API",
    version="1.1.0",
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes that must work before a session exists. Everything else under /api is
# rejected before it reaches a handler unless it carries a valid signature.
PUBLIC_API_PATHS = {"/api/auth/register", "/api/auth/login"}


@app.middleware("http")
async def require_signed_identity(request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    if path in PUBLIC_API_PATHS:
        return await call_next(request)

    try:
        verify_signature(
            request.headers.get("x-bids-user"),
            request.headers.get("x-bids-timestamp"),
            request.headers.get("x-bids-signature"),
        )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    return await call_next(request)


app.include_router(auth.router,         prefix="/api/auth",       tags=["Accounts"])
app.include_router(dashboard.router,    prefix="/api/dashboard",  tags=["Dashboard"])
app.include_router(behavior.router,     prefix="/api/behavior",   tags=["Behavior Analytics"])
app.include_router(segmentation.router, prefix="/api/segments",   tags=["Segmentation"])
app.include_router(rootcause.router,    prefix="/api/rootcause",  tags=["Root Cause Analysis"])
app.include_router(drift.router,        prefix="/api/drift",      tags=["Data Drift & BPR"])
app.include_router(forecast.router,     prefix="/api/forecast",   tags=["Forecasting"])
app.include_router(strategy.router,     prefix="/api/strategy",   tags=["Strategy AI"])
app.include_router(upload.router,       prefix="/api/upload",     tags=["Data Upload"])
app.include_router(analysis.router,     prefix="/api/analysis",   tags=["Analysis Report"])


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "system": "BIDS API v1.1"}
