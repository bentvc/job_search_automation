from database import SessionLocal
from models import Company, ProactiveOutreach, Contact
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JUNK_OFFENDERS = [
    'Tech A-Z','View All Jobs','Log In','Best Places To Work','For Employers',
    'Job Application Tracker','32 Benefits','38 Benefits','40 Benefits','42 Benefits',
    '52 Benefits','53 Benefits','54 Benefits','57 Benefits','59 Benefits','65 Benefits',
    '66 Benefits','75 Benefits','76 Benefits','23 Benefits','24 Benefits','26 Benefits',
    '31 Benefits','48 Benefits','57 Benefits','76 Benefits',
    'Jobs','Salaries','Companies','Hiring Now','Tech Hubs','Post Job','Our Story',
    'Careers','Tech Jobs','Recruit With Built In','Share Feedback','Report a Bug',
    'Customer Support','Create Free Account','Tech Job Tools + Career Resources',
    'Terms of Use','Copyright Policy','Your Privacy Choices/Cookie Settings',
    'Our Sites','Content Descriptions','Our Staff Writers','Tracker',
    'Become an Expert Contributor','Accessibility Statement','CA Notice of Collection',
    'Join', 'Articles', 'See Our Teams', 'View All Jobs', 'Our Story'
]

def purge_junk():
    db = SessionLocal()
    try:
        # 1. DELETE OUTREACH ASSOCIATED WITH JUNK
        junk_companies = db.query(Company).filter(Company.name.in_(JUNK_OFFENDERS)).all()
        junk_ids = [c.id for c in junk_companies]
        
        if junk_ids:
            num_outreach = db.query(ProactiveOutreach).filter(ProactiveOutreach.company_id.in_(junk_ids)).delete(synchronize_session=False)
            num_contacts = db.query(Contact).filter(Contact.company_id.in_(junk_ids)).delete(synchronize_session=False)
            num_companies = db.query(Company).filter(Company.name.in_(JUNK_OFFENDERS)).delete(synchronize_session=False)
            
            db.commit()
            logger.info(f"🗑 Purged {num_companies} junk companies.")
            logger.info(f"🗑 Purged {num_contacts} associated contacts.")
            logger.info(f"🗑 Purged {num_outreach} associated outreach items.")
        else:
            logger.info("No junk offenders found by name.")
            
        # 2. DELETE BY PATTERN (Any name ending in Digit + Benefits)
        # This is more proactive
        import re
        all_companies = db.query(Company).all()
        pattern = re.compile(r'^\d+\sBenefits$', re.I)
        to_delete = [c for c in all_companies if pattern.match(c.name)]
        if to_delete:
            del_ids = [c.id for c in to_delete]
            db.query(ProactiveOutreach).filter(ProactiveOutreach.company_id.in_(del_ids)).delete(synchronize_session=False)
            db.query(Contact).filter(Contact.company_id.in_(del_ids)).delete(synchronize_session=False)
            db.query(Company).filter(Company.id.in_(del_ids)).delete(synchronize_session=False)
            db.commit()
            logger.info(f"🗑 Purged {len(to_delete)} pattern-matched junk entries.")
            
    finally:
        db.close()

if __name__ == "__main__":
    purge_junk()
