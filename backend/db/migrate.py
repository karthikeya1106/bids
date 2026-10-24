"""
One-off schema migration: remove the globally shared demo tables.

Older builds stored orders, customers, KPIs, BPR rules and dataset metadata in
single global tables with no owner column, so every visitor saw the same demo
dataset. Those tables are backed up once next to the database file and dropped;
``create_all`` then rebuilds them with tenant-scoped keys.
"""
from __future__ import annotations

import os
import shutil

from sqlalchemy import inspect

LEGACY_TABLES = ("orders", "customers", "kpis", "bpr_rules", "dataset_meta")


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

    with engine.begin() as connection:
        for table in legacy:
            connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}"')

    print(
        "[migrate] Removed globally shared demo tables "
        f"({', '.join(legacy)}). Every workspace now starts empty."
    )
    return legacy
