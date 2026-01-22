"""
BONUS SCRAPER #6: Healthcare-Specific Job Boards
Scrapes specialized healthcare sales job boards (MedReps, HealthcareJobSite, etc.)
Expected: 500+ niche healthcare sales roles
"""
import logging
from database import SessionLocal
from models import Job
import requests
from bs4 import BeautifulSoup
import uuid
from datetime import datetime
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_medreps():
    """Scrape MedReps - medical sales job board"""
    try:
        url = "https://www.medreps.com/medical-sales-jobs"
        params = {
            'keywords': 'payer OR "health plan" OR enterprise OR strategic',
            'location': 'Remote'
        }
        
        response = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # MedReps job listings
        job_cards = soup.find_all('div', class_=lambda x: x and 'job' in str(x).lower())
        
        for card in job_cards[:100]:
            try:
                title_elem = card.find('a', class_=lambda x: x and 'title' in str(x).lower())
                if not title_elem:
                    title_elem = card.find('h2') or card.find('h3')
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                job_url = title_elem.get('href', '')
                
                if job_url and not job_url.startswith('http'):
                    job_url = f"https://www.medreps.com{job_url}"
                
                # Get company
                company_elem = card.find(lambda tag: tag.name in ['span', 'div'] and 'company' in str(tag.get('class', [])).lower())
                company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                
                # Get location
                location_elem = card.find(lambda tag: tag.name in ['span', 'div'] and 'location' in str(tag.get('class', [])).lower())
                location = location_elem.get_text(strip=True) if location_elem else "Unknown"
                
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': job_url,
                    'source': 'medreps'
                })
                
            except Exception as e:
                logger.debug(f"Error parsing MedReps job: {e}")
                continue
        
        logger.info(f"✅ MedReps: Found {len(jobs)} jobs")
        return jobs
        
    except Exception as e:
        logger.error(f"Error scraping MedReps: {e}")
        return []

def scrape_healthcarejobsite():
    """Scrape HealthcareJobSite.com"""
    try:
        url = "https://www.healthcarejobsite.com/jobs"
        params = {
            'q': 'sales enterprise payer',
            'l': 'Remote'
        }
        
        response = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Job listings
        job_items = soup.find_all('div', {'data-job-id': True}) or soup.find_all('article', class_=lambda x: x and 'job' in str(x).lower())
        
        for item in job_items[:100]:
            try:
                title_elem = item.find('h2') or item.find('a', class_=lambda x: x and 'title' in str(x).lower())
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                
                link_elem = item.find('a')
                job_url = link_elem.get('href', '') if link_elem else ""
                
                if job_url and not job_url.startswith('http'):
                    job_url = f"https://www.healthcarejobsite.com{job_url}"
                
                # Company
                company_elem = item.find(class_=lambda x: x and 'company' in str(x).lower())
                company = company_elem.get_text(strip=True) if company_elem else "Unknown"
                
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': 'Remote',
                    'url': job_url,
                    'source': 'healthcarejobsite'
                })
                
            except Exception as e:
                logger.debug(f"Error parsing HealthcareJobSite job: {e}")
                continue
        
        logger.info(f"✅ HealthcareJobSite: Found {len(jobs)} jobs")
        return jobs
        
    except Exception as e:
        logger.error(f"Error scraping HealthcareJobSite: {e}")
        return []

def scrape_health_ecareers():
    """Scrape Health eCareers"""
    try:
        url = "https://www.healthecareers.com/job/search"
        params = {
            'keywords': 'VP Sales OR CRO OR enterprise sales',
            'location': 'Remote'
        }
        
        response = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Job cards
        job_cards = soup.find_all('div', class_=lambda x: x and ('result' in str(x).lower() or 'card' in str(x).lower()))
        
        for card in job_cards[:100]:
            try:
                title_elem = card.find('a')
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                job_url = title_elem.get('href', '')
                
                if job_url and not job_url.startswith('http'):
                    job_url = f"https://www.healthecareers.com{job_url}"
                
                jobs.append({
                    'title': title,
                    'company': "Unknown",
                    'location': "Remote",
                    'url': job_url,
                    'source': 'health_ecareers'
                })
                
            except Exception as e:
                logger.debug(f"Error parsing Health eCareers job: {e}")
                continue
        
        logger.info(f"✅ Health eCareers: Found {len(jobs)} jobs")
        return jobs
        
    except Exception as e:
        logger.error(f"Error scraping Health eCareers: {e}")
        return []

def store_niche_jobs(jobs_data):
    """Store niche board jobs"""
    db = SessionLocal()
    try:
        stored_count = 0
        
        for job_data in jobs_data:
            dedupe_key = f"{job_data['source']}_{job_data['company']}_{job_data['title']}".lower().replace(" ", "_")
            
            existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
            if existing:
                continue
            
            new_job = Job(
                id=str(uuid.uuid4()),
                source=job_data['source'],
                title=job_data['title'],
                company_name=job_data['company'],
                location=job_data['location'],
                is_remote='remote' in job_data['location'].lower(),
                url=job_data['url'],
                date_posted=datetime.now(),
                description="",
                raw_data=job_data,
                dedupe_key=dedupe_key,
                status='new'
            )
            
            db.add(new_job)
            stored_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} niche healthcare jobs")
        return stored_count
        
    finally:
        db.close()

def run_niche_boards_scraper():
    """Main niche boards scraper"""
    logger.info("🏥 Launching Healthcare-Specific Job Board Scraper")
    
    all_jobs = []
    
    # Scrape MedReps
    logger.info("Scraping MedReps...")
    medreps_jobs = scrape_medreps()
    all_jobs.extend(medreps_jobs)
    time.sleep(2)
    
    # Scrape HealthcareJobSite
    logger.info("Scraping HealthcareJobSite...")
    hcjs_jobs = scrape_healthcarejobsite()
    all_jobs.extend(hcjs_jobs)
    time.sleep(2)
    
    # Scrape Health eCareers
    logger.info("Scraping Health eCareers...")
    hec_jobs = scrape_health_ecareers()
    all_jobs.extend(hec_jobs)
    
    logger.info(f"📊 Total scraped: {len(all_jobs)} jobs from niche boards")
    
    stored = store_niche_jobs(all_jobs)
    
    logger.info(f"✅ Niche Boards Complete: {stored} new healthcare sales jobs")
    return stored

if __name__ == "__main__":
    run_niche_boards_scraper()
