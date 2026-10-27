"""
Schema patches that run at startup.

1. Drop pre-tenant demo tables (backed up once).
2. Add columns introduced after the first tenant schema.
3. Rebuild ``dataset_meta`` when it still enforces one dataset per owner, so a
   workspace can keep several datasets and switch between them.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Optional

from sqlalchemy import inspect, text

LEGACY_TABLES = ("orders", "customers", "kpis", "bpr_rules", "dataset_meta")

DATASET_META_COLUMNS = {
    "dataset_type": "VARCHAR DEFAULT 'sales'",
    "schema_kind": "VARCHAR DEFAULT 'generic'",
    "analysis_task": "VARCHAR DEFAULT 'eda'",
    "target_field": "VARCHAR",
    "synthesized": "INTEGER DEFAULT 0",
    "is_active": "INTEGER DEFAULT 0",
    "materialized": "INTEGER DEFAULT 0",
    "profile_json": "TEXT",
    "mapping_json": "TEXT",
    "schema_json": "TEXT",
    "validation_json": "TEXT",
    "capabilities_json": "TEXT",
}

DATASET_META_DDL = """
CREATE TABLE dataset_meta (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    owner_id VARCHAR NOT NULL,
    dataset_name VARCHAR,
    org_name VARCHAR,
    source VARCHAR,
    dataset_type VARCHAR,
    schema_kind VARCHAR,
    analysis_task VARCHAR,
    target_field VARCHAR,
    synthesized INTEGER,
    row_count INTEGER,
    customer_count INTEGER,
    total_sales FLOAT,
    is_active INTEGER,
    materialized INTEGER,
    profile_json TEXT,
    mapping_json TEXT,
    schema_json TEXT,
    validation_json TEXT,
    capabilities_json TEXT,
    uploaded_at DATETIME
)
"""


def migrate_legacy_tables(engine) -> list[str]:
    """Drop pre-tenant tables (after backing up the SQLite file)."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    legacy = [
        table
        for table in LEGACY_TABLES
        if table in existing
        and "owner_id" not in {column["name"] for column in inspector.get_columns(table)}
    ]
    if not legacy:
        return []

    database = engine.url.database
    if engine.dialect.name == "sqlite" and database and os.path.exists(database):
        backup = f"{database}.legacy-demo-backup"
        if not os.path.exists(backup):
            shutil.copy2(database, backup)
            print(f"[migrate] Backed up the previous database to {backup}")

    if engine.dialect.name != "sqlite":
        # On a server database the whole instance cannot be copied cheaply, so
        # keep the pre-tenant tables under a dated name instead of dropping them.
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        with engine.begin() as connection:
            for table in legacy:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" RENAME TO "{table}_legacy_{stamp}"'
                )
        print(
            "[migrate] Parked legacy demo tables as "
            f"{', '.join(f'{table}_legacy_{stamp}' for table in legacy)}."
        )
        return legacy

    with engine.begin() as connection:
        for table in legacy:
            connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}"')

    print(
        "[migrate] Removed globally shared demo tables "
        f"({', '.join(legacy)}). Every workspace now starts empty."
    )
    return legacy


def _owner_unique(engine) -> tuple[Optional[str], Optional[str]]:
    """(kind, name) of the UNIQUE(owner_id) rule on dataset_meta, if present."""
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='dataset_meta'")
            ).fetchone()
        if row and "UNIQUE (owner_id)" in (row[0] or "").replace("\n", " "):
            return "sqlite-rebuild", "dataset_meta"
        return None, None

    inspector = inspect(engine)
    for constraint in inspector.get_unique_constraints("dataset_meta"):
        if constraint.get("column_names") == ["owner_id"]:
            return "constraint", constraint.get("name")
    for index in inspector.get_indexes("dataset_meta"):
        if index.get("unique") and index.get("column_names") == ["owner_id"]:
            return "index", index.get("name")
    return None, None


def _owner_unique_exists(engine) -> bool:
    kind, _ = _owner_unique(engine)
    return kind is not None


def _rebuild_dataset_meta(engine) -> None:
    """Recreate dataset_meta without the UNIQUE(owner_id) constraint."""
    if engine.dialect.name != "sqlite":
        # Postgres can drop the rule in place; no table copy needed.
        kind, name = _owner_unique(engine)
        if not name:
            return
        with engine.begin() as connection:
            if kind == "index":
                connection.exec_driver_sql(f'DROP INDEX IF EXISTS "{name}"')
            else:
                connection.exec_driver_sql(
                    f'ALTER TABLE dataset_meta DROP CONSTRAINT IF EXISTS "{name}"'
                )
        print("[migrate] dataset_meta: removed UNIQUE(owner_id); a workspace can hold several datasets.")
        return

    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("dataset_meta")}
    copy_columns = [column for column in DATASET_META_COLUMNS.keys() if column in existing_columns]
    copy_columns = ["id", "owner_id", "dataset_name", "org_name", "source"] + [
        column for column in copy_columns
        if column not in {"id", "owner_id", "dataset_name", "org_name", "source"}
    ]
    if "uploaded_at" in existing_columns:
        copy_columns.append("uploaded_at")

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE dataset_meta RENAME TO dataset_meta_legacy")
        connection.exec_driver_sql(DATASET_META_DDL)
        columns_sql = ", ".join(f'"{column}"' for column in copy_columns)
        connection.exec_driver_sql(
            f"INSERT INTO dataset_meta ({columns_sql}) SELECT {columns_sql} FROM dataset_meta_legacy"
        )
        connection.exec_driver_sql("DROP TABLE dataset_meta_legacy")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_dataset_meta_owner_id ON dataset_meta (owner_id)"
        )
    print("[migrate] dataset_meta rebuilt: a workspace can now hold multiple datasets.")


def ensure_schema(engine) -> None:
    """Add new columns and relax the dataset registry, without dropping data."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "dataset_meta" not in tables:
        return

    if _owner_unique_exists(engine):
        _rebuild_dataset_meta(engine)

    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns("dataset_meta")}
    with engine.begin() as connection:
        for name, ddl in DATASET_META_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE dataset_meta ADD COLUMN {name} {ddl}"))
        # Backfill the new registry fields for rows created before this version.
        connection.execute(text(
            "UPDATE dataset_meta SET schema_kind = dataset_type "
            "WHERE (schema_kind IS NULL OR schema_kind = '') AND dataset_type IS NOT NULL"
        ))
        # Only when a workspace has no active dataset yet (first launch after
        # this upgrade): promote its newest dataset. Never override a user's
        # explicit dataset switch on later startups.
        connection.execute(text(
            "UPDATE dataset_meta SET is_active = 1 "
            "WHERE id IN (SELECT MAX(id) FROM dataset_meta GROUP BY owner_id) "
            "AND owner_id NOT IN (SELECT owner_id FROM dataset_meta WHERE is_active = 1)"
        ))
