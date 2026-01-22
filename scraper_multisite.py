"""
FIXED: Multi-Site JobSpy with Retry Logic
Handles rate limits and blocks gracefully, continues with working sources
"""
import logging
import config
from database import SessionLocal
from models import Job
from jobspy import scrape_jobs
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_single_site_query(site, query, retry=True):
    """Scrape one query from one site with retry logic"""
    try:
        logger.info(f"🔍 {site}: '{query}'...")
        
        jobs_df = scrape_jobs(
            site_name=[site],  # Single site
            search_term=query,
            location="Remote",
            results_wanted=config.JOBSPY_RESULTS_PER_QUERY,
            hours_old=168,
            country_indeed='USA'
        )
        
        if jobs_df.empty:
            return []
        
        jobs = jobs_df.to_dict('records')
        logger.info(f"✅ {site}: Found {len(jobs)} jobs for '{query}'")
        return jobs
        
    except Exception as e:
        error_msg = str(e).lower()
        
        # Check if it's a rate limit or block
        if 'rate' in error_msg or 'block' in error_msg or 'captcha' in error_msg:
            logger.warning(f"⚠️ {site} blocked/rate-limited for '{query}'")
            
            if retry:
                logger.info(f"Retrying {site} in 5 seconds...")
                time.sleep(5)
                return scrape_single_site_query(site, query, retry=False)
        else:
            logger.error(f"❌ {site} error for '{query}': {e}")
        
        return []

def scrape_query_all_sites(query):
    """Scrape one query from all sites"""
    all_jobs = []
    
    for site in config.JOBSPY_SITES:
        jobs = scrape_single_site_query(site, query)
        all_jobs.extend(jobs)
        time.sleep(2)  # Rate limiting between sites
    
    return all_jobs

def deduplicate_and_store(all_jobs):
    """Store jobs with deduplication"""
    db = SessionLocal()
    try:
        stored_count = 0
        duplicate_count = 0
        
        for job_data in all_jobs:
            # Create dedupe key
            company = job_data.get('company', 'unknown')
            title = job_data.get('title', 'unknown')
            dedupe_key = f"{company}_{title}".lower().replace(" ", "_")[:255]
            
            # Check if exists
            existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
            if existing:
                duplicate_count += 1
                continue
            
            # Create new job
            new_job = Job(
                id=str(uuid.uuid4()),
                source=job_data.get('site', 'jobspy'),
                title=job_data.get('title'),
                company_name=job_data.get('company'),
                location=job_data.get('location'),
                is_remote='remote' in str(job_data.get('location', '')).lower(),
                url=job_data.get('job_url'),
                date_posted=datetime.now(),
                description=job_data.get('description', ''),
                raw_data=job_data,
                dedupe_key=dedupe_key,
                status='new'
            )
            
            db.add(new_job)
            stored_count += 1
            
            # Commit in batches
            if stored_count % 50 == 0:
                db.commit()
                logger.info(f"  💾 Committed {stored_count} jobs so far...")
        
        db.commit()
        logger.info(f"💾 Final: Stored {stored_count} new jobs, skipped {duplicate_count} duplicates")
        return stored_count
        
    finally:
        db.close()

def run_multisite_scraper():
    """Main entry point - parallel multi-site scraping with retry logic"""
    logger.info(f"🚀 Launching High-Volume Multi-Site Scraper (FIXED)")
    logger.info(f"📊 Config: {len(config.JOBSPY_QUERIES)} queries × {len(config.JOBSPY_SITES)} sites")
    logger.info(f"🌐 Sites: {', '.join(config.JOBSPY_SITES)}")
    
    all_jobs = []
    
    # Process queries sequentially to avoid overwhelming any single site
    for i, query in enumerate(config.JOBSPY_QUERIES):
        logger.info(f"\n[Query {i+1}/{len(config.JOBSPY_QUERIES)}]: {query}")
        jobs = scrape_query_all_sites(query)
        all_jobs.extend(jobs)
        logger.info(f"  Subtotal: {len(jobs)} jobs from this query")
    
    logger.info(f"\n🎯 Total jobs scraped: {len(all_jobs)}")
    
    # Store with deduplication
    stored = deduplicate_and_store(all_jobs)
    
    logger.info(f"✅ Multi-Site Scrape Complete: {stored} new jobs added")
    return stored

if __name__ == "__main__":
    run_multisite_scraper()
