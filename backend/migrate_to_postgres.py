"""Copy a local SQLite workspace into PostgreSQL (Supabase, Neon, local server).

This is a one-shot data migration, not a schema tool: the target schema is
created from the SQLAlchemy models, every row is copied table by table, identity
sequences are advanced past the copied ids and the row counts are verified
against the source before the script reports success.

Usage (from the backend directory, with the project virtualenv):

    # local PostgreSQL that is already running
    python migrate_to_postgres.py \
        --target postgresql://postgres:postgres@127.0.0.1:5432/bids_db --reset

    # Supabase: copy the connection string from Project settings -> Database
    python migrate_to_postgres.py --target "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres" --reset

    # see what would happen without writing anything
    python migrate_to_postgres.py --target ... --dry-run

After a successful run, put the same URL in backend/.env as DATABASE_URL.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent

# Copy order: parents first. There are no foreign keys declared, but keeping the
# natural order makes a partial failure easy to reason about.
TABLES = (
    "users",
    "dataset_meta",
    "dataset_rows",
    "customers",
    "orders",
    "churn_subscribers",
    "kpis",
    "bpr_rules",
)

BATCH = 2000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate the BIDS SQLite workspace to PostgreSQL.")
    parser.add_argument("--source", help="SQLite file to read (default: DATABASE_URL from .env)")
    parser.add_argument("--target", help="PostgreSQL URL to write (default: TARGET_DATABASE_URL)")
    parser.add_argument("--reset", action="store_true", help="Drop the BIDS tables on the target first")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    parser.add_argument("--batch", type=int, default=BATCH, help="Rows per insert batch")
    return parser.parse_args()


def _dotenv() -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - dotenv is a hard dependency
        return {}
    return {key: value for key, value in dotenv_values(BACKEND_DIR / ".env").items() if value}


def _resolve_source(arg: str | None, env: dict[str, str]) -> str:
    if arg:
        return arg if "://" in arg else f"sqlite:///{Path(arg).as_posix()}"
    configured = env.get("DATABASE_URL", "")
    if configured.startswith("sqlite:///"):
        return configured
    return f"sqlite:///{(BACKEND_DIR / 'bids.db').as_posix()}"


def _resolve_target(arg: str | None, env: dict[str, str]) -> str:
    target = arg or env.get("TARGET_DATABASE_URL", "")
    if not target:
        raise SystemExit(
            "No target database. Pass --target postgresql://... or set TARGET_DATABASE_URL."
        )
    if target.startswith("postgres://"):
        target = target.replace("postgres://", "postgresql://", 1)
    if not target.startswith("postgresql"):
        raise SystemExit(f"Target must be a PostgreSQL URL, got: {target.split('@')[-1]}")
    return target


def _models():
    from db import models  # imported after DATABASE_URL points at the target

    return models


def _source_session(source_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    source_engine = create_engine(
        source_url,
        connect_args={"check_same_thread": False} if source_url.startswith("sqlite") else {},
    )
    return source_engine, sessionmaker(bind=source_engine)()


def _table_counts(session, models) -> dict[str, int]:
    counts = {}
    for name in TABLES:
        model = getattr(models, _model_name(name))
        counts[name] = session.query(model).count()
    return counts


def _model_name(table: str) -> str:
    return {
        "users": "User",
        "dataset_meta": "DatasetMeta",
        "dataset_rows": "DatasetRow",
        "customers": "Customer",
        "orders": "Order",
        "churn_subscribers": "ChurnSubscriber",
        "kpis": "KPI",
        "bpr_rules": "BPRRule",
    }[table]


def _row_dicts(session, models, table: str, offset: int, limit: int) -> list[dict[str, Any]]:
    model = getattr(models, _model_name(table))
    columns = [column.name for column in model.__table__.columns]
    order = model.__table__.c.id if "id" in columns else None
    query = session.query(model)
    if order is not None:
        query = query.order_by(order)
    rows = query.offset(offset).limit(limit).all()
    return [{name: getattr(row, name) for name in columns} for row in rows]


def _reset_target(engine, models) -> None:
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in reversed(TABLES):
            if table in existing:
                connection.exec_driver_sql(f'DROP TABLE "{table}" CASCADE')
    print(f"[reset] dropped {', '.join(t for t in reversed(TABLES) if t in existing) or 'nothing'}")


def _park_legacy(engine) -> None:
    """Move pre-tenant demo tables out of the way instead of dropping them."""
    from db.migrate import migrate_legacy_tables

    parked = migrate_legacy_tables(engine)
    if parked:
        print(f"[legacy] parked {', '.join(parked)}")


def _advance_sequences(engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    serial_tables = ("dataset_meta", "dataset_rows", "orders", "kpis", "bpr_rules")
    with engine.begin() as connection:
        for table in serial_tables:
            connection.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), true)"
                )
            )
    print("[seq] identity sequences advanced past the copied ids")


def main() -> int:
    args = _parse_args()
    env = _dotenv()
    source_url = _resolve_source(args.source, env)
    target_url = _resolve_target(args.target, env)

    # db.database reads DATABASE_URL at import time; point it at the target so
    # the models, create_all and the ORM session all speak to PostgreSQL.
    os.environ["DATABASE_URL"] = target_url

    from sqlalchemy import create_engine, inspect

    from db.database import Base, engine
    from db.migrate import ensure_schema

    models = _models()
    source_engine, source_session = _source_session(source_url)

    if not inspect(source_engine).has_table("dataset_meta") and not inspect(source_engine).has_table("users"):
        raise SystemExit(f"Source {source_url} does not look like a BIDS database.")

    source_counts = _table_counts(source_session, models)
    print(f"[source] {source_url.split('@')[-1]}")
    for table, count in source_counts.items():
        print(f"  {table:<20} {count:>9,}")

    if args.dry_run:
        print(f"[dry-run] target {target_url.split('@')[-1]} would receive the rows above")
        return 0

    print(f"[target] {target_url.split('@')[-1]}")
    _park_legacy(engine)
    if args.reset:
        _reset_target(engine, models)
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)

    copied: dict[str, int] = {}
    for table in TABLES:
        total = source_counts[table]
        copied[table] = 0
        if total == 0:
            print(f"  {table:<20} empty, skipped")
            continue
        model = getattr(models, _model_name(table))
        for offset in range(0, total, args.batch):
            batch = _row_dicts(source_session, models, table, offset, args.batch)
            if not batch:
                break
            with engine.begin() as connection:
                connection.execute(model.__table__.insert(), batch)
            copied[table] += len(batch)
        print(f"  {table:<20} {copied[table]:>9,} rows copied")

    _advance_sequences(engine)

    # Verify from the target itself, not from the insert loop's bookkeeping.
    from sqlalchemy.orm import sessionmaker

    target_session = sessionmaker(bind=engine)()
    target_counts = _table_counts(target_session, models)
    target_session.close()
    source_session.close()

    print("\n[verify]")
    failures = 0
    for table in TABLES:
        match = source_counts[table] == target_counts[table]
        failures += 0 if match else 1
        print(
            f"  {table:<20} source {source_counts[table]:>8,} -> target {target_counts[table]:>8,}"
            f"  {'ok' if match else 'MISMATCH'}"
        )

    if failures:
        print(f"\n{failures} table(s) do not match. Nothing was deleted from the source; re-run with --reset.")
        return 1

    print("\nMigration complete. Put this in backend/.env to make it permanent:")
    print(f"  DATABASE_URL={target_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
