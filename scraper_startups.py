"""
QUICK WIN #4: Wellfound (AngelList) Healthcare Startup Directory
Scrape YC + healthcare startup universe for company intelligence & job signals
Expected: 500+ high-growth startups with funding data
"""
import logging
import config
from database import SessionLocal
from models import Company, CompanySignal
import requests
from bs4 import BeautifulSoup
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import time
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_yc_healthcare_companies():
    """Scrape Y Combinator healthcare companies"""
    try:
        url = "https://www.ycombinator.com/companies"
        params = {
            "industry": "Healthcare",
            "batch": "all"
        }
        
        response = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            logger.error(f"YC request failed: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        companies = []
        
        # YC company cards
        company_cards = soup.find_all('div', {'class': lambda x: x and '_company_' in str(x)})
        
        for card in company_cards[:200]:  # Limit to first 200
            try:
                # Extract company name
                name_elem = card.find('a', {'class': lambda x: x and 'company' in str(x).lower()})
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                url_path = name_elem.get('href', '')
                
                # Extract description
                desc_elem = card.find('div', {'class': lambda x: x and 'description' in str(x).lower()})
                description = desc_elem.get_text(strip=True) if desc_elem else ""
                
                # Extract batch/funding info if available
                batch_elem = card.find('div', {'class': lambda x: x and 'batch' in str(x).lower()})
                batch = batch_elem.get_text(strip=True) if batch_elem else "Unknown"
                
                companies.append({
                    'name': name,
                    'description': description,
                    'batch': batch,
                    'source': 'yc',
                    'url': f"https://www.ycombinator.com{url_path}" if url_path else ""
                })
                
            except Exception as e:
                logger.debug(f"Error parsing YC company card: {e}")
                continue
        
        logger.info(f"✅ YC: Found {len(companies)} healthcare companies")
        return companies
        
    except Exception as e:
        logger.error(f"Error scraping YC: {e}")
        return []

def scrape_wellfound_healthcare():
    """Scrape Wellfound (AngelList) for healthcare startups"""
    try:
        # Wellfound has different endpoints - we'll use search
        url = "https://wellfound.com/role/r/software-engineer"
        params = {
            "skill": "healthcare"
        }
        
        response = requests.get(url, params=params, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        companies = []
        
        # Wellfound company listings
        company_items = soup.find_all('div', {'data-test': 'StartupResult'})
        
        for item in company_items[:100]:
            try:
                name_elem = item.find('h2')
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                
                # Get company link
                link_elem = item.find('a')
                company_url = link_elem.get('href') if link_elem else ""
                
                # Get description
                desc_elem = item.find('p')
                description = desc_elem.get_text(strip=True) if desc_elem else ""
                
                companies.append({
                    'name': name,
                    'description': description,
                    'source': 'wellfound',
                    'url': f"https://wellfound.com{company_url}" if company_url and not company_url.startswith('http') else company_url
                })
                
            except Exception as e:
                logger.debug(f"Error parsing Wellfound company: {e}")
                continue
        
        logger.info(f"✅ Wellfound: Found {len(companies)} companies")
        return companies
        
    except Exception as e:
        logger.error(f"Error scraping Wellfound: {e}")
        return []

def store_startup_universe(companies_data):
    """Store startup companies in universe"""
    db = SessionLocal()
    try:
        stored_count = 0
        
        for comp_data in companies_data:
            # Check if exists
            existing = db.query(Company).filter(Company.name == comp_data['name']).first()
            if existing:
                continue
            
            # Determine vertical based on description
            desc_lower = comp_data['description'].lower()
            vertical = "other"
            
            if any(word in desc_lower for word in ['payer', 'health plan', 'insurance', 'medicaid', 'medicare']):
                vertical = "payer"
            elif any(word in desc_lower for word in ['healthcare', 'health', 'medical', 'clinical']):
                vertical = "healthcare"
            elif any(word in desc_lower for word in ['fintech', 'payment', 'billing']):
                vertical = "fintech"
            
            # Default fit score for YC/healthcare startups
            fit_score = 75  # High potential
            
            new_company = Company(
                id=str(uuid.uuid4()),
                name=comp_data['name'],
                domain=None,  # Will be enriched later
                vertical=vertical,
                fit_score=fit_score,
                monitoring_status='active',
                raw_data=comp_data
            )
            
            db.add(new_company)
            stored_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} startups in universe")
        return stored_count
        
    finally:
        db.close()

def run_startup_discovery():
    """Main startup discovery - YC + Wellfound"""
    logger.info("🚀 Launching Startup Universe Discovery")
    
    all_companies = []
    
    # Scrape YC
    logger.info("Scraping Y Combinator healthcare directory...")
    yc_companies = scrape_yc_healthcare_companies()
    all_companies.extend(yc_companies)
    
    # Scrape Wellfound
    logger.info("Scraping Wellfound healthcare startups...")
    wellfound_companies = scrape_wellfound_healthcare()
    all_companies.extend(wellfound_companies)
    
    logger.info(f"📊 Total discovered: {len(all_companies)} startups")
    
    # Store in universe
    stored = store_startup_universe(all_companies)
    
    logger.info(f"✅ Startup Discovery Complete: {stored} new companies added to universe")
    return stored

if __name__ == "__main__":
    run_startup_discovery()
