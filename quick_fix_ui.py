"""
Quick emergency fix: Copy fit scores from companies to outreach records
This is a fast patch while the full regeneration runs
"""
import logging
from database import SessionLocal
from models import ProactiveOutreach, Company

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def quick_fix_scores():
    """Copy company fit scores to outreach records immediately"""
    session = SessionLocal()
    try:
        outreach_records = session.query(ProactiveOutreach).filter(
            ProactiveOutreach.status.in_(['queued', 'snoozed'])
        ).all()
        
        updated = 0
        for outreach in outreach_records:
            if outreach.company and outreach.company.fit_score:
                outreach.fit_score = outreach.company.fit_score
                updated += 1
        
        session.commit()
        logger.info(f"✅ Updated {updated} outreach records with fit scores")
        
    finally:
        session.close()

if __name__ == "__main__":
    quick_fix_scores()
