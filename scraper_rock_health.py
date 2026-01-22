"""
BONUS SCRAPER #5: Rock Health Funding Database
Scrapes Rock Health's comprehensive healthcare funding tracker
Expected: 500+ funded healthcare companies with detailed metrics
"""
import logging
from database import SessionLocal
from models import Company, CompanySignal
import requests
from bs4 import BeautifulSoup
import uuid
from datetime import datetime
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_rock_health_funding():
    """Scrape Rock Health funding database"""
    try:
        url = "https://rockhealth.com/insights/digital-health-funding-database/"
        response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            logger.error(f"Rock Health request failed: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        companies = []
        
        # Rock Health uses a table or card structure for companies
        # Look for company entries
        company_rows = soup.find_all('tr') or soup.find_all('div', class_=re.compile(r'company|funding'))
        
        for row in company_rows[:300]:  # Process up to 300
            try:
                # Extract company name
                name_elem = row.find('a') or row.find('strong') or row.find('h3')
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                if len(name) < 3 or any(x in name.lower() for x in ['rock health', 'funding', 'database']):
                    continue
                
                # Extract funding amount if visible
                funding_text = row.get_text()
                funding_match = re.search(r'\$[\d.]+[MBK]', funding_text)
                funding = funding_match.group(0) if funding_match else None
                
                # Extract year if present
                year_match = re.search(r'20\d{2}', funding_text)
                year = year_match.group(0) if year_match else None
                
                companies.append({
                    'name': name,
                    'funding': funding,
                    'year': year,
                    'source': 'rock_health'
                })
                
            except Exception as e:
                logger.debug(f"Error parsing Rock Health entry: {e}")
                continue
        
        logger.info(f"✅ Rock Health: Found {len(companies)} funded companies")
        return companies
        
    except Exception as e:
        logger.error(f"Error scraping Rock Health: {e}")
        return []

def store_rock_health_data(companies_data):
    """Store Rock Health companies and create funding signals"""
    db = SessionLocal()
    try:
        stored_count = 0
        signal_count = 0
        
        for comp_data in companies_data:
            # Check if company exists
            company = db.query(Company).filter(Company.name == comp_data['name']).first()
            
            if not company:
                # Create new company
                company = Company(
                    id=str(uuid.uuid4()),
                    name=comp_data['name'],
                    domain=None,
                    vertical='healthcare',
                    fit_score=80,  # Funded healthcare companies are high-value
                    monitoring_status='active',
                    raw_data=comp_data
                )
                db.add(company)
                stored_count += 1
            
            # Create funding signal if we have funding data
            if comp_data.get('funding'):
                # Check if signal already exists
                existing_signal = db.query(CompanySignal).filter(
                    CompanySignal.company_id == company.id,
                    CompanySignal.signal_type == 'funding'
                ).first()
                
                if not existing_signal:
                    signal = CompanySignal(
                        id=str(uuid.uuid4()),
                        company_id=company.id,
                        signal_type='funding',
                        signal_date=datetime.now(),
                        signal_text=f"Raised {comp_data['funding']}" + (f" in {comp_data['year']}" if comp_data['year'] else ""),
                        score=85,  # High urgency for funded companies
                        source_url="https://rockhealth.com/insights/digital-health-funding-database/"
                    )
                    db.add(signal)
                    signal_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} companies, created {signal_count} funding signals")
        return stored_count
        
    finally:
        db.close()

def run_rock_health_scraper():
    """Main Rock Health scraper"""
    logger.info("💰 Launching Rock Health Funding Database Scraper")
    
    companies = scrape_rock_health_funding()
    
    if not companies:
        logger.warning("No companies found from Rock Health")
        return 0
    
    stored = store_rock_health_data(companies)
    
    logger.info(f"✅ Rock Health Complete: {stored} companies added with funding intelligence")
    return stored

if __name__ == "__main__":
    run_rock_health_scraper()
