#!/usr/bin/env python3
"""
Test script: Generate sample drafts with MiniMax API vs Local DeepSeek
Compare quality, speed, and cost for both approaches with Perplexity verification.
"""
import logging
import time
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from sync_leads import generate_outreach_content

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_generation():
    session = SessionLocal()
    
    # Get 3 diverse test cases
    test_cases = session.query(ProactiveOutreach).join(Company).filter(
        ProactiveOutreach.company_id.isnot(None)
    ).limit(3).all()
    
    if not test_cases:
        logger.error("No outreach records found to test")
        return
    
    results = []
    
    for idx, outreach in enumerate(test_cases, 1):
        company = session.query(Company).get(outreach.company_id)
        contact = session.query(Contact).get(outreach.contact_id) if outreach.contact_id else None
        job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
        
        if not company or not contact:
            continue
        
        logger.info(f"\n{'='*80}")
        logger.info(f"TEST CASE {idx}: {company.name} ({company.vertical or 'unknown'})")
        logger.info(f"Contact: {contact.name} - {contact.title}")
        logger.info(f"{'='*80}\n")
        
        # Test 1: MiniMax API (fast, cheap)
        logger.info("🚀 METHOD 1: MiniMax API + Verification")
        start_time = time.time()
        try:
            content_minimax = generate_outreach_content(
                company, contact, job=job, signal=None,
                use_local=False,  # Use MiniMax API
                verify=True       # With verification
            )
            minimax_time = time.time() - start_time
            
            logger.info(f"✅ MiniMax completed in {minimax_time:.1f}s")
            logger.info(f"Verification: {'✅ PASSED' if content_minimax.get('verification_passed') else '⚠️ FLAGGED'}")
            if content_minimax.get('verification_issues'):
                logger.warning(f"Issues: {content_minimax['verification_issues']}")
            
            results.append({
                'company': company.name,
                'method': 'MiniMax API',
                'time': minimax_time,
                'verified': content_minimax.get('verification_passed', False),
                'content': content_minimax
            })
        except Exception as e:
            logger.error(f"❌ MiniMax failed: {e}")
            minimax_time = 0
            content_minimax = None
        
        logger.info("\n" + "-"*80 + "\n")
        
        # Test 2: Local DeepSeek (slow, free)
        logger.info("🏠 METHOD 2: Local DeepSeek + Verification")
        start_time = time.time()
        try:
            content_local = generate_outreach_content(
                company, contact, job=job, signal=None,
                use_local=True,   # Use local DeepSeek
                verify=True       # With verification
            )
            local_time = time.time() - start_time
            
            logger.info(f"✅ Local DeepSeek completed in {local_time:.1f}s")
            logger.info(f"Verification: {'✅ PASSED' if content_local.get('verification_passed') else '⚠️ FLAGGED'}")
            if content_local.get('verification_issues'):
                logger.warning(f"Issues: {content_local['verification_issues']}")
            
            results.append({
                'company': company.name,
                'method': 'Local DeepSeek',
                'time': local_time,
                'verified': content_local.get('verification_passed', False),
                'content': content_local
            })
        except Exception as e:
            logger.error(f"❌ Local DeepSeek failed: {e}")
            local_time = 0
            content_local = None
        
        # Print comparison
        logger.info(f"\n{'='*80}")
        logger.info(f"COMPARISON FOR {company.name}:")
        logger.info(f"  MiniMax:       {minimax_time:.1f}s")
        logger.info(f"  Local DeepSeek: {local_time:.1f}s")
        if minimax_time > 0 and local_time > 0:
            logger.info(f"  Speed ratio:    {local_time/minimax_time:.1f}x slower (local)")
        logger.info(f"{'='*80}\n")
        
        # Print draft previews
        if content_minimax and content_minimax.get('draft_email'):
            logger.info("📧 MINIMAX DRAFT:")
            logger.info(content_minimax['draft_email'][:300] + "...\n")
        
        if content_local and content_local.get('draft_email'):
            logger.info("📧 LOCAL DRAFT:")
            logger.info(content_local['draft_email'][:300] + "...\n")
        
        logger.info("\n" + "="*80 + "\n")
    
    # Final summary
    logger.info("\n" + "="*80)
    logger.info("FINAL SUMMARY")
    logger.info("="*80)
    
    minimax_results = [r for r in results if r['method'] == 'MiniMax API']
    local_results = [r for r in results if r['method'] == 'Local DeepSeek']
    
    if minimax_results:
        avg_minimax_time = sum(r['time'] for r in minimax_results) / len(minimax_results)
        minimax_verified = sum(1 for r in minimax_results if r['verified'])
        logger.info(f"\nMiniMax API:")
        logger.info(f"  Avg time: {avg_minimax_time:.1f}s")
        logger.info(f"  Verified: {minimax_verified}/{len(minimax_results)}")
        logger.info(f"  Cost estimate: ${len(minimax_results) * 0.004:.3f}")
    
    if local_results:
        avg_local_time = sum(r['time'] for r in local_results) / len(local_results)
        local_verified = sum(1 for r in local_results if r['verified'])
        logger.info(f"\nLocal DeepSeek:")
        logger.info(f"  Avg time: {avg_local_time:.1f}s")
        logger.info(f"  Verified: {local_verified}/{len(local_results)}")
        logger.info(f"  Cost estimate: $0.000 (FREE)")
    
    if minimax_results and local_results:
        logger.info(f"\nSpeed comparison: Local is {avg_local_time/avg_minimax_time:.1f}x slower than MiniMax")
        logger.info(f"Cost for 24 records:")
        logger.info(f"  MiniMax: ${24 * 0.004:.2f}")
        logger.info(f"  Local:   $0.00")
    
    logger.info("\n" + "="*80)
    logger.info("RECOMMENDATION:")
    if minimax_results and local_results:
        if avg_local_time > 120:  # If local takes >2 minutes per record
            logger.info("  Use MiniMax API for batch generation (faster, still cheap)")
            logger.info("  Cost: ~$0.10 for all 24 records")
        else:
            logger.info("  Local DeepSeek is acceptable if you can wait ~60-90 minutes")
            logger.info("  MiniMax is 10x faster for just $0.10 total")
    logger.info("="*80)
    
    session.close()

if __name__ == "__main__":
    test_generation()
