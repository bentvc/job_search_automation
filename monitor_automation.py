#!/usr/bin/env python3
"""
Real-Time Pipeline Progress Monitor
Shows which phase is running and live statistics
"""
import sqlite3
import time
import subprocess
from datetime import datetime

def check_running_processes():
    """Check which scrapers are currently running"""
    processes = {
        'multi-site': 'scraper_multisite.py',
        'batch_scorer': 'batch_scorer.py',
        'yc': 'scraper_yc_fixed.py',
        'ats': 'scraper_ats.py',
        'rock_health': 'scraper_rock_health.py',
        'niche_boards': 'scraper_niche_boards.py',
        'rss': 'scraper_rss_funding.py',
        'sync': 'sync_leads.py'
    }
    
    running = []
    for name, process in processes.items():
        try:
            result = subprocess.run(['pgrep', '-f', process], capture_output=True)
            if result.returncode == 0:
                running.append(name)
        except:
            pass
    
    return running

def get_stats():
    """Get current database stats"""
    try:
        conn = sqlite3.connect('data/job_search.db')
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute("SELECT COUNT(*) FROM jobs")
        stats['total_jobs'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE status='shortlisted'")
        stats['shortlisted'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM companies WHERE monitoring_status='active'")
        stats['companies'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM proactive_outreach WHERE status='queued'")
        stats['queued_outreach'] = cursor.fetchone()[0]
        
        # Get recent adds (last 5 minutes)
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE datetime(created_at) > datetime('now', '-5 minutes')")
        stats['jobs_last_5min'] = cursor.fetchone()[0]
        
        conn.close()
        return stats
    except Exception as e:
        return {'error': str(e)}

def print_status():
    """Print current status"""
    print("\n" + "="*70)
    print(f"🤖 AUTOMATED PIPELINE STATUS - {datetime.now().strftime('%H:%M:%S')}")
    print("="*70)
    
    # Check what's running
    running = check_running_processes()
    
    if running:
        print(f"\n🔄 CURRENTLY RUNNING:")
        for proc in running:
            print(f"   ▶ {proc.replace('_', ' ').title()}")
    else:
        print("\n⏸️  No active scrapers (may be between phases or complete)")
    
    # Show stats
    stats = get_stats()
    
    if 'error' not in stats:
        print(f"\n📊 CURRENT TOTALS:")
        print(f"   Total Jobs:        {stats['total_jobs']:,}")
        print(f"   Shortlisted:       {stats['shortlisted']:,}")
        print(f"   Active Companies:  {stats['companies']:,}")
        print(f"   Queued Outreach:   {stats['queued_outreach']:,}")
        print(f"\n📈 RECENT ACTIVITY:")
        print(f"   Jobs (last 5 min): +{stats['jobs_last_5min']}")
    
    print("\n" + "="*70)
    print("📝 Logs: tail -f automated_pipeline.log")
    print("📊 Full Monitor: python monitor_pipeline.py")
    print("="*70)

if __name__ == "__main__":
    print("🚀 Real-Time Pipeline Monitor")
    print("Press Ctrl+C to stop monitoring\n")
    
    try:
        while True:
            print_status()
            time.sleep(15)  # Update every 15 seconds
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")
