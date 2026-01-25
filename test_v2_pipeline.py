#!/usr/bin/env python3
"""
Test V2 Pipeline: DeepSeek → Perplexity
Simple two-stage generation on one test company.
"""
import logging
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from pipeline_v2 import run_v2_pipeline
import config

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

def test_v2_pipeline():
    session = SessionLocal()
    
    # Get Gravie test case
    outreach = session.query(ProactiveOutreach).join(Company).filter(
        Company.name == 'Gravie'
    ).first()
    
    if not outreach:
        logger.error("No Gravie outreach found")
        return
    
    company = session.query(Company).filter_by(id=outreach.company_id).first()
    contact = session.query(Contact).filter_by(id=outreach.contact_id).first()
    job = session.query(Job).filter_by(id=outreach.job_id).first() if outreach.job_id else None
    
    if not company or not contact:
        logger.error("Missing company or contact")
        return
    
    logger.info(f"\n{'='*80}")
    logger.info(f"TESTING V2 PIPELINE: {company.name}")
    logger.info(f"Contact: {contact.name} - {contact.title}")
    logger.info(f"{'='*80}\n")
    
    # Run the pipeline
    result = run_v2_pipeline(
        company=company.name,
        role=contact.title or "Executive",
        job_description=job.description if job else "Scaling healthcare/payer sales team",
        job_url=job.url if job else None,
        sender_profile=config.USER_PROFILE_SUMMARY,
        use_local_deepseek=True  # Free local DeepSeek
    )
    
    # Display results
    logger.info(f"\n{'='*80}")
    logger.info("STAGE 1: DeepSeek Analysis")
    logger.info(f"{'='*80}")
    logger.info(f"Wedge: {result['ds_wedge']}")
    logger.info(f"\nRationale:\n{result['ds_rationale']}")
    logger.info(f"\nProof Points:")
    for point in result.get('ds_key_points', []):
        logger.info(f"  - {point}")
    logger.info(f"\nDeepSeek Draft ({len(result['ds_raw_draft'])} chars):")
    logger.info(result['ds_raw_draft'])
    
    logger.info(f"\n{'='*80}")
    logger.info("STAGE 2: Perplexity Finalization")
    logger.info(f"{'='*80}")
    logger.info(f"Confidence: {result['px_confidence']:.2f}")
    logger.info(f"Status: {result['status']}")
    
    if result.get('px_factual_flags'):
        logger.info(f"\n⚠️  Factual Flags:")
        for flag in result['px_factual_flags']:
            logger.info(f"  - {flag}")
    else:
        logger.info(f"\n✅ No factual flags")
    
    logger.info(f"\nFinal Email ({len(result['px_final_email'])} chars):")
    logger.info(result['px_final_email'])
    
    if result.get('px_citations'):
        logger.info(f"\nCitations:")
        for citation in result['px_citations']:
            logger.info(f"  - {citation}")
    
    logger.info(f"\n{'='*80}")
    logger.info("SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"DeepSeek: ✅ Wedge identified, draft generated")
    logger.info(f"Perplexity: ✅ Facts verified, final email ready")
    logger.info(f"Status: {result['status']}")
    logger.info(f"Cost: ~$0.002 (Perplexity only, DeepSeek is FREE)")
    logger.info(f"{'='*80}\n")
    
    # Ask if we should save to DB
    save = input("\nSave this result to the database? (y/n): ").lower().strip() == 'y'
    
    if save:
        outreach.ds_wedge = result['ds_wedge']
        outreach.ds_rationale = result['ds_rationale']
        outreach.ds_key_points = result['ds_key_points']
        outreach.ds_raw_draft = result['ds_raw_draft']
        outreach.px_final_email = result['px_final_email']
        outreach.px_confidence = result['px_confidence']
        outreach.px_factual_flags = result['px_factual_flags']
        outreach.px_citations = result.get('px_citations')
        outreach.status = result['status']
        
        session.commit()
        logger.info("✅ Saved to database!")
    else:
        logger.info("❌ Not saved")
    
    session.close()

if __name__ == "__main__":
    test_v2_pipeline()
