from database import SessionLocal
from models import Job, JobScore
from sqlalchemy import func
import hashlib

def cleanup_duplicates():
    db = SessionLocal()
    try:
        # 1. First, find all jobs
        all_jobs = db.query(Job).all()
        seen_keys = {} # key -> primary_job_id
        
        for job in all_jobs:
            # Re-calculate dedupe key based on new logic (company + cleaned title)
            title = job.title.lower().strip()
            company = job.company_name.lower().strip()
            clean_title = title.split('(@')[0].split(' - ')[0].strip()
            
            key_str = f"{company}|{clean_title}"
            new_key = hashlib.md5(key_str.encode()).hexdigest()
            
            if new_key in seen_keys:
                primary_id = seen_keys[new_key]
                print(f"Merging duplicate: {job.title} ({job.id}) -> {primary_id}")
                
                # Move any scores to the primary job if they don't exist
                # (Simple: just delete the duplicate)
                db.delete(job)
            else:
                seen_keys[new_key] = job.id
                job.dedupe_key = new_key # Update the key in DB
        
        db.commit()
        print("Cleanup complete.")
    finally:
        db.close()

if __name__ == "__main__":
    cleanup_duplicates()
