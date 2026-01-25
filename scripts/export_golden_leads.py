import yaml
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import GoldenLead

def export_golden_leads():
    db = SessionLocal()
    try:
        leads = db.query(GoldenLead).order_by(GoldenLead.company_name).all()
        if not leads:
            print("⚠️ No golden leads found in DB.")
            return

        data = []
        for l in leads:
            data.append({
                "company_name": l.company_name,
                "vertical": l.vertical,
                "location": l.location,
                "expected_fit_tier": l.expected_fit_tier,
                "expected_lead_type": l.expected_lead_type,
                "is_local": bool(l.is_local),
                "notes": l.notes
            })

        output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'golden_leads.yaml')
        with open(output_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)
        
        print(f"✅ Exported {len(leads)} golden leads to {output_path}")
    finally:
        db.close()

if __name__ == "__main__":
    export_golden_leads()
