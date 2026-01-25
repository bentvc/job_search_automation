import yaml
import os
import uuid
import sys
from datetime import datetime

# Add parent directory to path to import models and database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import Company, ProactiveOutreach, Job, GoldenLead

def prepare_golden_set(test_run_id="golden_set_v1", imported_only=False):
    db = SessionLocal()
    try:
        # Check if golden_leads table is empty
        db_leads = db.query(GoldenLead).all()
        
        if not db_leads or imported_only:
            print("📥 Importing from YAML to DB table...")
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'golden_leads.yaml')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    yaml_leads = yaml.safe_load(f)
                
                # Clear and re-fill if imported_only
                if imported_only:
                    db.query(GoldenLead).delete()
                
                for l in yaml_leads:
                    gl = GoldenLead(
                        id=str(uuid.uuid4()),
                        company_name=l['company_name'],
                        vertical=l['vertical'],
                        location=l['location'],
                        expected_fit_tier=l['expected_fit_tier'],
                        expected_lead_type=l['expected_lead_type'],
                        is_local=l.get('is_local', False),
                        notes=l.get('notes', '')
                    )
                    db.add(gl)
                db.commit()
                db_leads = db.query(GoldenLead).all()
                print(f"✅ Synced {len(db_leads)} leads from YAML to DB.")

        if not db_leads:
            print("⚠️ No golden leads available in DB or YAML.")
            return

        # Clear existing test run data if any
        db.query(ProactiveOutreach).filter(ProactiveOutreach.test_run_id == test_run_id).delete()
        
        for lead in db_leads:
            company_name = lead.company_name
            print(f"Provisioning {company_name}...")
            
            # Find or create company
            company = db.query(Company).filter(Company.name == company_name).first()
            if not company:
                company = Company(
                    id=str(uuid.uuid4()),
                    name=company_name,
                    vertical=lead.vertical,
                    hq_location=lead.location,
                    fit_score=0 
                )
                db.add(company)
                db.flush()
            else:
                company.vertical = lead.vertical
                company.hq_location = lead.location

            lead_type = lead.expected_lead_type
            job_id = None
            if lead_type == 'job_posting':
                job = Job(
                    id=str(uuid.uuid4()),
                    company_id=company.id,
                    company_name=company.name,
                    title="Strategic Account Executive",
                    description="Enterprise sales role. Medicaid/Medicare experience a plus.",
                    status='shortlisted',
                    location=company.hq_location
                )
                db.add(job)
                db.flush()
                job_id = job.id

            outreach = ProactiveOutreach(
                id=str(uuid.uuid4()),
                company_id=company.id,
                job_id=job_id,
                lead_type=lead_type,
                outreach_type='job_intro' if lead_type == 'job_posting' else 'signal_intro',
                status='queued',
                test_run_id=test_run_id,
                fit_explanation=f"GOLDEN SET: Expected {lead.expected_fit_tier}",
                test_scores={"expected_tier": lead.expected_fit_tier}
            )
            db.add(outreach)
            
        db.commit()
        print(f"✅ Successfully prepared evaluation set with {len(db_leads)} leads. test_run_id: {test_run_id}")
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-yaml", action="store_true", help="Force import from YAML to DB")
    parser.add_argument("--id", default="golden_set_v1")
    args = parser.parse_args()
    
    prepare_golden_set(test_run_id=args.id, imported_only=args.import_yaml)
