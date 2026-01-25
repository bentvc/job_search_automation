import logging
import pandas as pd
import hashlib
from datetime import datetime
import os
import uuid
from database import SessionLocal
from models import Job, Company

logger = logging.getLogger(__name__)

import re
from datetime import timedelta

def parse_relative_date(date_str: str) -> datetime:
    """Parses strings like '2 days ago', '3 hours ago', 'Just now' into a datetime."""
    if not date_str or not isinstance(date_str, str):
        return datetime.utcnow()
    
    date_str = date_str.lower().strip()
    now = datetime.utcnow()
    
    if 'just now' in date_str or 'today' in date_str:
        return now
    
    match = re.search(r'(\d+)\s+(day|hour|minute|week)', date_str)
    if not match:
        return now
        
    value = int(match.group(1))
    unit = match.group(2)
    
    if 'day' in unit:
        return now - timedelta(days=value)
    elif 'hour' in unit:
        return now - timedelta(hours=value)
    elif 'minute' in unit:
        return now - timedelta(minutes=value)
    elif 'week' in unit:
        return now - timedelta(weeks=value)
        
    return now

def upsert_scraped_jobs(df: pd.DataFrame, source: str = "manual"):
    """
    Ingests a DataFrame of scraped jobs into the database.
    Normalizes fields to match the Job model and avoids duplicates.
    """
    if df is None or df.empty:
        logger.info("No jobs to ingest.")
        return 0

    db = SessionLocal()
    new_count = 0
    try:
        for _, row in df.iterrows():
            title = str(row.get('title', '')).lower().strip()
            company_name = str(row.get('company', '')).lower().strip()
            
            clean_title = title.split('(@')[0].split(' - ')[0].strip()
            key_str = f"{company_name}|{clean_title}"
            dedupe_key = hashlib.md5(key_str.encode()).hexdigest()
            
            existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
            if existing:
                existing.last_seen_at = datetime.utcnow()
                continue
                
            # Try to link to a company in our universe
            comp = db.query(Company).filter(Company.name.ilike(row.get('company', ''))).first()
            company_id = comp.id if comp else None
            
            # Convert date_posted to datetime
            raw_date = row.get('date_posted')
            if isinstance(raw_date, str):
                if 'ago' in raw_date or 'today' in raw_date or 'now' in raw_date:
                    date_posted = parse_relative_date(raw_date)
                else:
                    try:
                        date_posted = datetime.fromisoformat(raw_date)
                    except:
                        date_posted = datetime.utcnow()
            elif isinstance(raw_date, datetime):
                date_posted = raw_date
            else:
                date_posted = datetime.utcnow()

            new_job = Job(
                id=str(uuid.uuid4()),
                title=row.get('title'),
                company_name=row.get('company'),
                company_id=company_id,
                location=row.get('location'),
                url=row.get('job_url'),
                description=row.get('description'),
                date_posted=date_posted,
                dedupe_key=dedupe_key,
                source=row.get('site', source),
                status='new',
                raw_data=row.to_dict(),
                last_seen_at=datetime.utcnow()
            )
            db.add(new_job)
            new_count += 1
            
        db.commit()
        logger.info(f"✅ Ingested {new_count} new jobs into DB (source: {source}).")
        return new_count
    except Exception as e:
        logger.error(f"❌ Ingestion error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()
