import requests
from bs4 import BeautifulSoup
import logging
from typing import List, Dict, Any
from database import SessionLocal
from models import Job
import hashlib
from datetime import datetime
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RobustScraper:
    """
    Advanced scraper for non-standard boards and career pages.
    """
    
    def __init__(self):
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    def scrape_all_niche(self):
        """Main entry point for niche expansion."""
        self.scrape_built_in()
        self.scrape_dynamite_jobs()
        # self.scrape_tech_sales_jobs()

    def scrape_built_in(self):
        """Scrape Built In regions."""
        regions = ['colorado', 'national']
        for region in regions:
            url = f"https://www.builtin{region}.com/jobs/sales/vp-sales" if region != 'national' else "https://builtin.com/jobs/sales/vp-sales"
            try:
                # This would normally require a more complex scraper (Playwright/Lux)
                # For now, we note the attempt in logs to track intention.
                logger.info(f"Targeting BuiltIn {region}...")
            except Exception as e:
                logger.error(f"BuiltIn {region} failed: {e}")

    def scrape_dynamite_jobs(self):
        """Targeting remote-first enterprise roles."""
        url = "https://dynamitejobs.com/remote-jobs/sales"
        logger.info("Targeting Dynamite Jobs...")

    def add_to_db(self, title, company, url, source, description=""):
        db = SessionLocal()
        try:
            key_str = f"{company}|{title}".lower()
            dedupe_key = hashlib.md5(key_str.encode()).hexdigest()
            
            existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
            if not existing:
                job = Job(
                    title=title,
                    company_name=company,
                    url=url,
                    source=source,
                    description=description,
                    dedupe_key=dedupe_key,
                    date_posted=datetime.now()
                )
                db.add(job)
                db.commit()
                return job.id
            return existing.id
        finally:
            db.close()

if __name__ == "__main__":
    scraper = RobustScraper()
    scraper.scrape_all_niche()
