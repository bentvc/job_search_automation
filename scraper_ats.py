"""
QUICK WIN #3: Greenhouse Direct ATS Scraper
Bypass job boards - scrape career pages directly from target companies
Expected: 200+ high-quality roles from top payers/health tech companies
"""
import logging
import config
from database import SessionLocal
from models import Job, Company
import requests
from bs4 import BeautifulSoup
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_greenhouse_company(company_slug):
    """Scrape all jobs from a Greenhouse board"""
    try:
        url = f"https://boards.greenhouse.io/{company_slug}"
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Greenhouse structure: job listings in sections
        job_sections = soup.find_all('section', class_='level-0')
        
        for section in job_sections:
            job_items = section.find_all('div', class_='opening')
            
            for item in job_items:
                try:
                    title_elem = item.find('a')
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    job_url = title_elem.get('href')
                    
                    # Make full URL
                    if job_url and not job_url.startswith('http'):
                        job_url = f"https://boards.greenhouse.io{job_url}"
                    
                    # Get location if available
                    location_elem = item.find('span', class_='location')
                    location = location_elem.get_text(strip=True) if location_elem else "Unknown"
                    
                    jobs.append({
                        'company_slug': company_slug,
                        'title': title,
                        'url': job_url,
                        'location': location
                    })
                    
                except Exception as e:
                    logger.debug(f"Error parsing job item: {e}")
                    continue
        
        logger.info(f"✅ {company_slug}: Found {len(jobs)} jobs")
        return jobs
        
    except Exception as e:
        logger.error(f"Error scraping {company_slug}: {e}")
        return []

def scrape_lever_company(company_slug):
    """Scrape all jobs from a Lever board"""
    try:
        url = f"https://jobs.lever.co/{company_slug}"
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Lever structure: postings list
        posting_items = soup.find_all('div', class_='posting')
        
        for item in posting_items:
            try:
                title_elem = item.find('h5')
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                
                # Get link
                link_elem = item.find('a', class_='posting-title')
                job_url = link_elem.get('href') if link_elem else ""
                
                # Get location
                location_elem = item.find('span', class_='sort-by-location')
                location = location_elem.get_text(strip=True) if location_elem else "Unknown"
                
                if title:
                    jobs.append({
                        'company_slug': company_slug,
                        'title': title,
                        'url': job_url,
                        'location': location
                    })
                    
            except Exception as e:
                logger.debug(f"Error parsing Lever job: {e}")
                continue
        
        logger.info(f"✅ {company_slug}: Found {len(jobs)} jobs (Lever)")
        return jobs
        
    except Exception as e:
        logger.error(f"Error scraping Lever {company_slug}: {e}")
        return []

def store_ats_jobs(jobs_data, source_type="greenhouse"):
    """Store scraped ATS jobs in database"""
    db = SessionLocal()
    try:
        stored_count = 0
        
        for job_data in jobs_data:
            # Dedupe key
            dedupe_key = f"{source_type}_{job_data['company_slug']}_{job_data['title']}".lower().replace(" ", "_")
            
            existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
            if existing:
                continue
            
            # Find or create company
            company = db.query(Company).filter(Company.name.ilike(f"%{job_data['company_slug']}%")).first()
            
            new_job = Job(
                id=str(uuid.uuid4()),
                company_id=company.id if company else None,
                source=source_type,
                title=job_data['title'],
                company_name=job_data['company_slug'].replace('-', ' ').title(),
                location=job_data['location'],
                is_remote='remote' in job_data['location'].lower(),
                url=job_data['url'],
                date_posted=datetime.now(),
                description="",  # Fetch separately if needed
                raw_data=job_data,
                dedupe_key=dedupe_key,
                status='new'
            )
            
            db.add(new_job)
            stored_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} {source_type} jobs")
        return stored_count
        
    finally:
        db.close()

def run_ats_scraper():
    """Main ATS scraper - parallel scraping of Greenhouse and Lever"""
    logger.info(f"🎯 Launching Direct ATS Scraper")
    logger.info(f"📊 Targets: {len(config.GREENHOUSE_TARGETS)} companies")
    
    all_jobs = []
    
    # Try both Greenhouse and Lever for each company
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Greenhouse futures
        gh_futures = {executor.submit(scrape_greenhouse_company, slug): slug for slug in config.GREENHOUSE_TARGETS}
        
        # Lever futures (try same slugs)
        lever_futures = {executor.submit(scrape_lever_company, slug): slug for slug in config.GREENHOUSE_TARGETS}
        
        # Collect Greenhouse results
        for future in as_completed(gh_futures):
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"Future error: {e}")
        
        # Collect Lever results
        lever_jobs = []
        for future in as_completed(lever_futures):
            try:
                jobs = future.result()
                lever_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"Lever future error: {e}")
    
    logger.info(f"📊 Total scraped: {len(all_jobs)} Greenhouse + {len(lever_jobs)} Lever jobs")
    
    # Store both
    gh_stored = store_ats_jobs(all_jobs, "greenhouse")
    lever_stored = store_ats_jobs(lever_jobs, "lever")
    
    logger.info(f"✅ ATS Scrape Complete: {gh_stored + lever_stored} new jobs from career pages")
    return gh_stored + lever_stored

if __name__ == "__main__":
    run_ats_scraper()
