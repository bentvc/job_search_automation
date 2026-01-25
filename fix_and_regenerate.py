"""
Comprehensive fix: regenerate all outreach with proper Council insights and scoring.
"""
import logging
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from sync_leads import generate_outreach_content
from enhanced_scoring import recalculate_company_fit_score
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_all_outreach():
    """
    Fix all existing outreach records:
    1. Recalculate company fit scores
    2. Regenerate insights and drafts using the new Council system
    3. Update fit scores on outreach records
    """
    session = SessionLocal()
    try:
        # Step 1: Recalculate company fit scores
        logger.info("=" * 60)
        logger.info("STEP 1: Recalculating company fit scores...")
        logger.info("=" * 60)
        
        companies = session.query(Company).filter(Company.monitoring_status == 'active').all()
        for i, company in enumerate(companies, 1):
            logger.info(f"[{i}/{len(companies)}] Scoring {company.name}...")
            try:
                recalculate_company_fit_score(company.id)
            except Exception as e:
                logger.error(f"Error scoring {company.name}: {e}")
        
        session.commit()
        logger.info("✅ Company scoring complete\n")
        
        # Step 2: Regenerate all outreach with Council
        logger.info("=" * 60)
        logger.info("STEP 2: Regenerating outreach with Council insights...")
        logger.info("=" * 60)
        
        all_outreach = session.query(ProactiveOutreach).filter(
            ProactiveOutreach.status.in_(['queued', 'snoozed'])
        ).all()
        
        logger.info(f"Found {len(all_outreach)} outreach records to regenerate\n")
        
        for i, outreach in enumerate(all_outreach, 1):
            logger.info(f"[{i}/{len(all_outreach)}] Processing {outreach.company.name if outreach.company else 'Unknown'}...")
            
            try:
                # Get related objects
                company = session.query(Company).get(outreach.company_id)
                contact = session.query(Contact).get(outreach.contact_id) if outreach.contact_id else None
                job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
                
                if not company:
                    logger.warning(f"  ⚠️  No company found, skipping")
                    continue
                
                if not contact:
                    # Try to find a contact for this company
                    contact = session.query(Contact).filter(
                        Contact.company_id == company.id
                    ).order_by(Contact.confidence_score.desc()).first()
                    
                    if contact:
                        outreach.contact_id = contact.id
                        logger.info(f"  → Found contact: {contact.name}")
                    else:
                        logger.warning(f"  ⚠️  No contact found for {company.name}, skipping")
                        continue
                
                # Generate signal text
                signal = outreach.signal_summary or "High-fit target company"
                if job:
                    signal = f"Job Posting: {job.title}"
                
                # Use the new Council system with verification (LOCAL - FREE!)
                logger.info(f"  → Calling Council for insights (with Perplexity verification)...")
                content = generate_outreach_content(
                    company, contact, job=job, signal=signal, 
                    use_local=True,  # Free local DeepSeek
                    verify=True      # Perplexity fact-checking
                )
                
                if content and content.get('draft_email'):
                    # Update outreach with new content
                    outreach.insights = content.get('insights', '')
                    outreach.draft_email = content.get('draft_email', '')
                    outreach.fit_explanation = content.get('outreach_angle', '')
                    outreach.fit_score = company.fit_score or 0
                    
                    # Update signal summary if it was generic
                    if not outreach.signal_summary or outreach.signal_summary == "Direct Universe Outreach":
                        if job:
                            outreach.signal_summary = f"Job: {job.title}"
                        else:
                            outreach.signal_summary = f"High-fit company ({company.fit_score} score)"
                    
                    session.commit()
                    logger.info(f"  ✅ Updated (fit_score: {company.fit_score}, has insights: {bool(content.get('insights'))})")
                else:
                    logger.warning(f"  ⚠️  Council returned no content")
                
                # Rate limit to avoid API issues
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"  ❌ Error: {e}")
                session.rollback()
                continue
        
        logger.info("\n" + "=" * 60)
        logger.info("REGENERATION COMPLETE")
        logger.info("=" * 60)
        
        # Final summary
        total = session.query(ProactiveOutreach).count()
        with_insights = session.query(ProactiveOutreach).filter(
            ProactiveOutreach.insights != None,
            ProactiveOutreach.insights != ''
        ).count()
        with_scores = session.query(ProactiveOutreach).filter(
            ProactiveOutreach.fit_score > 0
        ).count()
        
        logger.info(f"\n📊 Final Stats:")
        logger.info(f"  Total outreach records: {total}")
        logger.info(f"  With Council insights: {with_insights}")
        logger.info(f"  With fit scores > 0: {with_scores}")
        
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("🚀 Starting comprehensive fix and regeneration...\n")
    fix_all_outreach()
    logger.info("\n✅ All done! Refresh your UI to see the changes.")
