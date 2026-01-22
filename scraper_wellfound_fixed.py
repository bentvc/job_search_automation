"""
FIXED: Wellfound (AngelList) Scraper
Updated for current site structure + added search alternatives
"""
import logging
from database import SessionLocal
from models import Company
import requests
from bs4 import BeautifulSoup
import uuid
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_wellfound_healthcare():
    """Scrape Wellfound with updated selectors"""
    companies = []
    
    # Try multiple search approaches
    search_queries = [
        ('healthcare', 'Health Care'),
        ('health-tech', 'Health Tech'),
        ('digital-health', 'Digital Health'),
        ('payer', 'Healthcare Payer'),
        ('healthtech', 'HealthTech')
    ]
    
    for query_slug, query_name in search_queries:
        try:
            # Wellfound company search
            url = f"https://wellfound.com/companies"
            params = {
                'markets[]': query_slug
            }
            
            logger.info(f"Searching Wellfound for: {query_name}")
            
            response = requests.get(
                url,
                params=params,
                timeout=15,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"Wellfound {query_name} failed: {response.status_code}")
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple selectors for company cards
            selectors_to_try = [
                ('div', {'data-test': 'StartupResult'}),
                ('div', {'class': lambda x: x and 'startup' in str(x).lower()}),
                ('a', {'class': lambda x: x and 'company' in str(x).lower()}),
                ('div', {'class': lambda x: x and 'result' in str(x).lower()}),
            ]
            
            found_count = 0
            for tag, attrs in selectors_to_try:
                items = soup.find_all(tag, attrs)
                
                if items:
                    logger.info(f"  Found {len(items)} companies with selector: {tag} {attrs}")
                    
                    for item in items[:50]:  # Limit per query
                        try:
                            # Extract company name
                            name_elem = item.find(['h2', 'h3', 'h4', 'a'])
                            if not name_elem:
                                continue
                            
                            name = name_elem.get_text(strip=True)
                            
                            # Skip if too short or looks like navigation
                            if len(name) < 3 or any(x in name.lower() for x in ['view', 'more', 'filter', 'search']):
                                continue
                            
                            # Get company link
                            link_elem = item.find('a', href=True)
                            company_url = link_elem.get('href', '') if link_elem else ""
                            
                            if company_url and not company_url.startswith('http'):
                                company_url = f"https://wellfound.com{company_url}"
                            
                            # Get description if available
                            desc_elem = item.find('p') or item.find('div', {'class': lambda x: x and 'desc' in str(x).lower()})
                            description = desc_elem.get_text(strip=True) if desc_elem else ""
                            
                            companies.append({
                                'name': name,
                                'description': description,
                                'url': company_url,
                                'source': f'wellfound_{query_slug}',
                                'market': query_name
                            })
                            found_count += 1
                            
                        except Exception as e:
                            logger.debug(f"Error parsing Wellfound item: {e}")
                            continue
                    
                    if found_count > 0:
                        break  # Found companies with this selector
            
            time.sleep(2)  # Rate limiting
            
        except Exception as e:
            logger.error(f"Error scraping Wellfound {query_name}: {e}")
            continue
    
    # Deduplicate by name
    unique_companies = {}
    for comp in companies:
        if comp['name'] not in unique_companies:
            unique_companies[comp['name']] = comp
    
    companies = list(unique_companies.values())
    logger.info(f"✅ Wellfound: Found {len(companies)} unique companies")
    return companies

def scrape_wellfound_via_api():
    """Try Wellfound's GraphQL API (if accessible)"""
    try:
        # Wellfound sometimes has a GraphQL endpoint
        url = "https://wellfound.com/graphql"
        
        query = """
        query {
          startups(markets: ["healthcare", "health-tech"]) {
            name
            one_liner
            website
          }
        }
        """
        
        response = requests.post(
            url,
            json={'query': query},
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Content-Type': 'application/json'
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'startups' in data['data']:
                companies = []
                for startup in data['data']['startups']:
                    companies.append({
                        'name': startup.get('name'),
                        'description': startup.get('one_liner', ''),
                        'website': startup.get('website', ''),
                        'source': 'wellfound_api'
                    })
                logger.info(f"✅ Wellfound API: Found {len(companies)} companies")
                return companies
        
        return []
        
    except Exception as e:
        logger.debug(f"Wellfound API not accessible: {e}")
        return []

def store_wellfound_companies(companies_data):
    """Store Wellfound companies"""
    db = SessionLocal()
    try:
        stored_count = 0
        
        for comp_data in companies_data:
            name = comp_data.get('name', '').strip()
            if not name or len(name) < 3:
                continue
            
            # Check exists
            existing = db.query(Company).filter(Company.name == name).first()
            if existing:
                continue
            
            # Determine vertical
            desc = comp_data.get('description', '').lower()
            vertical = 'healthcare'
            if 'payer' in desc or 'insurance' in desc:
                vertical = 'payer'
            elif 'fintech' in desc or 'payment' in desc:
                vertical = 'fintech'
            
            # Extract domain if available
            domain = None
            if comp_data.get('website'):
                domain = comp_data['website'].replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            
            new_company = Company(
                id=str(uuid.uuid4()),
                name=name,
                domain=domain,
                vertical=vertical,
                fit_score=80,
                monitoring_status='active',
                raw_data=comp_data
            )
            
            db.add(new_company)
            stored_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} Wellfound companies")
        return stored_count
        
    finally:
        db.close()

def run_wellfound_scraper():
    """Main Wellfound scraper"""
    logger.info("🌟 Launching Wellfound Healthcare Scraper (FIXED)")
    
    # Try API first
    companies = scrape_wellfound_via_api()
    
    # Fall back to HTML scraping
    if not companies:
        companies = scrape_wellfound_healthcare()
    
    if not companies:
        logger.error("All Wellfound scrape methods failed")
        return 0
    
    stored = store_wellfound_companies(companies)
    
    logger.info(f"✅ Wellfound Complete: {stored} startups added")
    return stored

if __name__ == "__main__":
    run_wellfound_scraper()
