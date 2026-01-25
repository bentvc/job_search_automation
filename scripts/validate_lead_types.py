import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import LeadCategorizationAudit, ProactiveOutreach

def validate_lead_types():
    db = SessionLocal()
    try:
        print("--- Lead Categorization Audit Report ---")
        
        # 1. Mismatches between detected and final
        mismatches = db.query(LeadCategorizationAudit).filter(
            (LeadCategorizationAudit.job_posting_detected == True) & (LeadCategorizationAudit.final_lead_type != "job_posting")
        ).all()
        
        if mismatches:
            print(f"\n⚠️ FOUND {len(mismatches)} JOB POSTING MISMATCHES:")
            for m in mismatches:
                print(f"  - Company: {m.company_name}, Expected: job_posting, Actual: {m.final_lead_type} (Source: {m.signal_source})")
        else:
            print("\n✅ No job posting mismatches found.")

        # 2. Hybrid detection issues
        # (This would need more complex logic if we expect a specific combination)
        
        # 3. Summary of types
        from sqlalchemy import func
        stats = db.query(LeadCategorizationAudit.final_lead_type, func.count(LeadCategorizationAudit.id)).group_by(LeadCategorizationAudit.final_lead_type).all()
        print("\nDistribution of final lead types:")
        for lead_type, count in stats:
            print(f"  - {lead_type}: {count}")
            
    finally:
        db.close()

if __name__ == "__main__":
    validate_lead_types()
