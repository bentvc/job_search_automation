"""
FIXED: Y Combinator Healthcare Startup Scraper
Updated selectors for current YC website structure + API fallback
"""
import logging
from database import SessionLocal
from models import Company
import requests
import uuid
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_yc_via_api():
    """Use YC's unofficial API endpoint"""
    try:
        # YC has a JSON endpoint for their company directory
        url = "https://www.ycombinator.com/companies/industry/healthcare"
        
        response = requests.get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            },
            timeout=15
        )
        
        if response.status_code != 200:
            logger.error(f"YC request failed: {response.status_code}")
            return []
        
        # YC embeds company data in a script tag as JSON
        html = response.text
        companies = []
                # Look for the React data structure
        if '"companies":' in html:
            # Extract JSON data
            try:
                start = html.find('"companies":')
                if start > 0:
                    # Find the array bounds
                    bracket_start = html.find('[', start)
                    if bracket_start > 0:
                        # Count brackets to find matching close
                        bracket_count = 1
                        pos = bracket_start + 1
                        
                        while bracket_count > 0 and pos < len(html):
                            if html[pos] == '[':
                                bracket_count += 1
                            elif html[pos] == ']':
                                bracket_count -= 1
                            pos += 1
                        
                        if bracket_count == 0:
                            companies_json = html[bracket_start:pos]
                            companies_data = json.loads(companies_json)
                            logger.info(f"✅ YC API: Found {len(companies_data)} companies")
                            
                            # Process companies
                            for comp in companies_data[:300]:  # Limit to 300
                                if isinstance(comp, dict):
                                    companies.append({
                                        'name': comp.get('name', ''),
                                        'description': comp.get('one_liner', ''),
                                        'batch': comp.get('batch', ''),
                                        'website': comp.get('website', ''),
                                        'source': 'yc_api'
                                    })
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"JSON parse error: {e}")
        
        if companies:
            return companies
        
        # Fallback: Parse HTML manually
        logger.info("API extraction failed, trying HTML parsing...")
        return scrape_yc_via_html(html)
        
    except Exception as e:
        logger.error(f"YC API scrape error: {e}")
        return []

def scrape_yc_via_html(html=None):
    """Fallback HTML parser for YC"""
    try:
        if not html:
            url = "https://www.ycombinator.com/companies/industry/healthcare"
            response = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            html = response.text
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        companies = []
        
        # YC uses various structures - try multiple selectors
        selectors_to_try = [
            ('a', {'class': lambda x: x and 'company' in str(x).lower()}),
            ('div', {'data-company': True}),
            ('div', {'class': lambda x: x and '_company' in str(x)}),
        ]
        
        for tag, attrs in selectors_to_try:
            items = soup.find_all(tag, attrs)
            if items:
                logger.info(f"Found {len(items)} items with {tag} {attrs}")
                for item in items[:200]:
                    try:
                        name = item.get_text(strip=True)
                        if len(name) > 3 and len(name) < 100:
                            companies.append({
                                'name': name,
                                'description': '',
                                'batch': 'Unknown',
                                'source': 'yc_html'
                            })
                    except:
                        continue
                
                if companies:
                    break
        
        logger.info(f"✅ YC HTML: Found {len(companies)} companies")
        return companies
        
    except Exception as e:
        logger.error(f"YC HTML parse error: {e}")
        return []

def store_yc_companies(companies_data):
    """Store YC companies in database"""
    db = SessionLocal()
    try:
        stored_count = 0
        
        for comp_data in companies_data:
            name = comp_data.get('name', '').strip()
            if not name or len(name) < 3:
                continue
            
            # Check if exists
            existing = db.query(Company).filter(Company.name == name).first()
            if existing:
                continue
            
            # Extract domain from website if available
            domain = None
            website = comp_data.get('website', '')
            if website:
                domain = website.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            
            new_company = Company(
                id=str(uuid.uuid4()),
                name=name,
                domain=domain,
                vertical='healthcare',
                fit_score=85,  # YC healthcare companies are high-value
                monitoring_status='active',
                raw_data=comp_data
            )
            
            db.add(new_company)
            stored_count += 1
        
        db.commit()
        logger.info(f"💾 Stored {stored_count} YC companies")
        return stored_count
        
    finally:
        db.close()

def run_yc_scraper():
    """Main YC scraper with fallbacks"""
    logger.info("🚀 Launching Y Combinator Healthcare Scraper (FIXED)")
    
    # Try API first
    companies = scrape_yc_via_api()
    
    # If API fails, try direct HTML
    if not companies:
        logger.info("API failed, trying direct HTML scrape...")
        companies = scrape_yc_via_html()
    
    if not companies:
        logger.error("All YC scrape methods failed")
        return 0
    
    stored = store_yc_companies(companies)
    
    logger.info(f"✅ YC Scraper Complete: {stored} healthcare startups added")
    return stored

if __name__ == "__main__":
    run_yc_scraper()
