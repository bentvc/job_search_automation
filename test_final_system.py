#!/usr/bin/env python3
"""
Final Test: Generate 3 drafts with fixed MiniMax M2.1 + Adjusted Verification
"""
import logging
import time
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from sync_leads import generate_outreach_content

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

def test_final():
    session = SessionLocal()
    
    # Get 3 diverse test cases
    test_cases = session.query(ProactiveOutreach).join(Company).filter(
        ProactiveOutreach.company_id.isnot(None)
    ).limit(3).all()
    
    if not test_cases:
        logger.error("No outreach records found")
        return
    
    results = []
    
    for idx, outreach in enumerate(test_cases, 1):
        company = session.query(Company).get(outreach.company_id)
        contact = session.query(Contact).get(outreach.contact_id) if outreach.contact_id else None
        job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
        
        if not company or not contact:
            continue
        
        logger.info(f"\n{'='*80}")
        logger.info(f"TEST {idx}/3: {company.name}")
        logger.info(f"Contact: {contact.name} - {contact.title}")
        logger.info(f"{'='*80}")
        
        start_time = time.time()
        
        try:
            content = generate_outreach_content(
                company, contact, job=job, signal=None,
                use_local=False,  # Use MiniMax M2.1 API
                verify=True       # With adjusted verification
            )
            
            elapsed = time.time() - start_time
            
            # Check results
            passed = content.get('verification_passed', False)
            failed = content.get('verification_failed', False)
            issues = content.get('verification_issues', [])
            
            logger.info(f"\n✅ Generated in {elapsed:.1f}s")
            logger.info(f"Verification: {'✅ PASSED' if passed else '⚠️ FLAGGED' if failed else '❓ SKIPPED'}")
            
            if issues:
                logger.info(f"Issues: {issues}")
            
            # Print draft
            draft = content.get('draft_email', 'No draft')
            logger.info(f"\n📧 DRAFT ({len(draft)} chars):")
            logger.info(f"{draft[:400]}...")
            
            # Print insights
            insights = content.get('insights', 'No insights')
            logger.info(f"\n🧙 INSIGHTS:")
            logger.info(f"{insights[:300]}...")
            
            results.append({
                'company': company.name,
                'time': elapsed,
                'verified': passed,
                'flagged': failed,
                'draft_length': len(draft)
            })
            
        except Exception as e:
            logger.error(f"❌ Failed: {e}")
            results.append({
                'company': company.name,
                'error': str(e)
            })
        
        logger.info(f"\n{'='*80}\n")
    
    # Summary
    logger.info(f"\n{'='*80}")
    logger.info("FINAL SUMMARY")
    logger.info(f"{'='*80}")
    
    successful = [r for r in results if 'error' not in r]
    verified = [r for r in successful if r.get('verified')]
    flagged = [r for r in successful if r.get('flagged')]
    
    logger.info(f"\nGeneration: {len(successful)}/{len(results)} successful")
    logger.info(f"Verification: {len(verified)} passed, {len(flagged)} flagged")
    
    if successful:
        avg_time = sum(r['time'] for r in successful) / len(successful)
        logger.info(f"Avg time: {avg_time:.1f}s per draft")
        logger.info(f"Cost estimate: ${len(successful) * 0.004:.3f}")
        logger.info(f"For 24 records: ~{24 * avg_time / 60:.1f} minutes, ${24 * 0.004:.2f}")
    
    logger.info(f"\n{'='*80}")
    logger.info("NEXT STEPS:")
    logger.info("  1. If results look good → Run full regeneration")
    logger.info("  2. If too many flagged → Adjust verification further")
    logger.info("  3. Command: python3 fix_and_regenerate.py")
    logger.info(f"{'='*80}\n")
    
    session.close()

if __name__ == "__main__":
    test_final()
