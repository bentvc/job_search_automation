#!/usr/bin/env python3
"""
Real-time pipeline monitoring dashboard
Shows live progress of all scrapers
"""
import sqlite3
import time
from datetime import datetime

def get_stats():
    """Query current database stats"""
    conn = sqlite3.connect('data/job_search.db')
    cursor = conn.cursor()
    
    stats = {}
    
    # Total jobs by status
    cursor.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
    stats['jobs_by_status'] = dict(cursor.fetchall())
    
    # Jobs by source
    cursor.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source ORDER BY COUNT(*) DESC")
    stats['jobs_by_source'] = cursor.fetchall()
    
    # Total companies
    cursor.execute("SELECT COUNT(*) FROM companies WHERE monitoring_status='active'")
    stats['active_companies'] = cursor.fetchone()[0]
    
    # Funding signals
    cursor.execute("SELECT COUNT(*) FROM company_signals WHERE signal_type='funding'")
    stats['funding_signals'] = cursor.fetchone()[0]
    
    # Outreach queue
    cursor.execute("SELECT COUNT(*) FROM proactive_outreach WHERE status='queued'")
    stats['queued_outreach'] = cursor.fetchone()[0]
    
    conn.close()
    return stats

def print_dashboard():
    """Print formatted dashboard"""
    stats = get_stats()
    
    print("\n" + "="*60)
    print(f"📊 JOB SEARCH PIPELINE - LIVE STATS")
    print(f"⏰ Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    print("\n📁 JOBS BY STATUS")
    print("-"*60)
    total_jobs = sum(stats['jobs_by_status'].values())
    print(f"  Total Jobs:      {total_jobs:,}")
    for status, count in stats['jobs_by_status'].items():
        pct = (count/total_jobs*100) if total_jobs > 0 else 0
        print(f"    └─ {status.ljust(12)}: {count:4,} ({pct:5.1f}%)")
    
    print("\n🌐 JOBS BY SOURCE")
    print("-"*60)
    for source, count in stats['jobs_by_source'][:10]:
        print(f"  {source.ljust(20)}: {count:4,}")
    
    print("\n🏢 COMPANY INTELLIGENCE")
    print("-"*60)
    print(f"  Active Companies:     {stats['active_companies']:,}")
    print(f"  Funding Signals:      {stats['funding_signals']:,}")
    print(f"  Queued Outreach:      {stats['queued_outreach']:,}")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    print("🚀 Starting real-time monitor (Ctrl+C to stop)")
    
    try:
        while True:
            print_dashboard()
            time.sleep(10)  # Update every 10 seconds
    except KeyboardInterrupt:
        print("\n\n👋 Monitor stopped")
