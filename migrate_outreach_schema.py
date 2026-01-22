#!/usr/bin/env python3
"""
Migration script to add new fields to ProactiveOutreach table.
Safe for SQLite - uses ALTER TABLE to add columns if they don't exist.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DATABASE_PATH", "job_search.db")

def get_existing_columns(cursor, table_name):
    """Get existing column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}

def migrate():
    print(f"🔄 Migrating database: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    existing_cols = get_existing_columns(cursor, 'proactive_outreach')
    print(f"   Existing columns: {sorted(existing_cols)}")
    
    migrations = [
        ("job_id", "VARCHAR(36)", None),
        ("fit_score", "INTEGER", 0),
        ("next_action_at", "DATETIME", None),
        ("outreach_type", "VARCHAR(50)", "'job_intro'"),
    ]
    
    for col_name, col_type, default in migrations:
        if col_name not in existing_cols:
            default_clause = f" DEFAULT {default}" if default is not None else ""
            sql = f"ALTER TABLE proactive_outreach ADD COLUMN {col_name} {col_type}{default_clause}"
            print(f"   ➕ Adding column: {col_name}")
            cursor.execute(sql)
        else:
            print(f"   ✅ Column exists: {col_name}")
    
    # Update status defaults for existing rows
    cursor.execute("""
        UPDATE proactive_outreach 
        SET status = 'queued' 
        WHERE status IS NULL OR status = ''
    """)
    
    # Update outreach_type defaults
    cursor.execute("""
        UPDATE proactive_outreach 
        SET outreach_type = 'job_intro' 
        WHERE outreach_type IS NULL OR outreach_type = '' OR outreach_type = 'intro'
    """)
    
    # Set next_action_at to now for all queued items that don't have it set
    cursor.execute("""
        UPDATE proactive_outreach 
        SET next_action_at = datetime('now') 
        WHERE status = 'queued' AND next_action_at IS NULL
    """)
    
    conn.commit()
    conn.close()
    
    print("✅ Migration complete!")

if __name__ == "__main__":
    migrate()
