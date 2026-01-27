#!/usr/bin/env python3
"""Add scored_at, promoted_at, prelim_vertical to discovery_candidates if missing. Safe to re-run."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import text
from database import engine

def migrate():
    with engine.begin() as conn:
        for col, typ in [
            ("scored_at", "DATETIME"),
            ("promoted_at", "DATETIME"),
            ("prelim_vertical", "VARCHAR(100)"),
            ("discovery_rank", "INTEGER"),
            ("discovery_score", "INTEGER"),
            ("canonical_company_name", "VARCHAR(255)"),
            ("entity_confidence", "INTEGER"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE discovery_candidates ADD COLUMN {col} {typ}"))
                print(f"Added column {col}")
            except Exception as e:
                err = str(e).lower()
                if "duplicate column" in err or "already exists" in err:
                    print(f"Column {col} already exists, skip")
                else:
                    raise
    print("Migration done.")

if __name__ == "__main__":
    migrate()
