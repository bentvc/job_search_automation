import sqlite3
import os

db_path = "data/job_search.db"
conn = sqlite3.connect(db_path)
curr = conn.cursor()

def add_column(table, column, type):
    try:
        curr.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type};")
        print(f"Added {column} to {table}")
    except sqlite3.OperationalError:
        print(f"Column {column} already exists in {table}")

# Contact updates
add_column("contacts", "status", "VARCHAR(50) DEFAULT 'new'")
add_column("contacts", "followup_stage", "INTEGER DEFAULT 0")
add_column("contacts", "last_contacted_at", "DATETIME")
add_column("contacts", "next_followup_due", "DATETIME")

# ProactiveOutreach updates
add_column("proactive_outreach", "outreach_type", "VARCHAR(50) DEFAULT 'intro'")

conn.commit()
conn.close()
