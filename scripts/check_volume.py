import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import Job, CompanySignal, Company

def check_volume(days=14):
    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        print(f"Checking volume since {cutoff.strftime('%Y-%m-%d')} ({days} days)...")
        
        # Total counts
        job_count = db.query(Job).filter(Job.created_at >= cutoff).count()
        signal_count = db.query(CompanySignal).filter(CompanySignal.created_at >= cutoff).count()
        
        print(f"\nTotal Volume:")
        print(f"  - New Job Postings: {job_count}")
        print(f"  - New Signal Events: {signal_count}")
        
        # Per vertical analysis
        from sqlalchemy import func
        vertical_jobs = db.query(Company.vertical, func.count(Job.id)).join(Job).filter(Job.created_at >= cutoff).group_by(Company.vertical).all()
        
        print("\nJobs by Vertical:")
        for vert, count in vertical_jobs:
            print(f"  - {vert or 'Unknown'}: {count}")
            
        # Companies with zero activity
        active_comps = db.query(Company).filter(Company.monitoring_status == 'active').all()
        silent_comps = []
        for comp in active_comps:
            has_job = db.query(Job).filter(Job.company_id == comp.id, Job.created_at >= cutoff).first()
            has_sig = db.query(CompanySignal).filter(CompanySignal.company_id == comp.id, CompanySignal.created_at >= cutoff).first()
            if not has_job and not has_sig:
                silent_comps.append(comp.name)
        
        if silent_comps:
            print(f"\n🔇 {len(silent_comps)} active companies with ZERO activity in the last {days} days.")
            if len(silent_comps) > 10:
                print(f"  Examples: {', '.join(silent_comps[:10])}...")
            else:
                print(f"  List: {', '.join(silent_comps)}")
        else:
            print("\n✅ All active companies had some activity.")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_volume()
