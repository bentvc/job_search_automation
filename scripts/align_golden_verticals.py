import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import Company, GoldenLead

def align_verticals():
    db = SessionLocal()
    try:
        golden_leads = db.query(GoldenLead).all()
        print(f"Aligning {len(golden_leads)} verticals from Golden Leads to production Companies...")
        
        for gl in golden_leads:
            company = db.query(Company).filter(Company.name.ilike(f"%{gl.company_name}%")).first()
            if company:
                if company.vertical != gl.vertical:
                    print(f"  {company.name}: {company.vertical} -> {gl.vertical}")
                    company.vertical = gl.vertical
            else:
                print(f"  ❌ {gl.company_name} not found in companies table")
        
        db.commit()
        print("✅ Alignment complete.")
    finally:
        db.close()

if __name__ == "__main__":
    align_verticals()
