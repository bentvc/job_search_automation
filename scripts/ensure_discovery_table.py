#!/usr/bin/env python3
"""Create discovery_candidates (and any missing tables) in the app DB. Run from repo root."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from database import init_db, DATABASE_URL

def main():
    init_db()
    path = DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
    print(f"Tables created. App DB path: {path}")
    print("Inspect: sqlite3", path, '".tables"')

if __name__ == "__main__":
    main()
