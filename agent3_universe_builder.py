import requests
from bs4 import BeautifulSoup
import logging
import json
from typing import List, Dict, Any
import config
from database import SessionLocal
from models import Company
from utils import call_llm, parse_json_from_llm
from rate_limiter import rate_limit
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Strict boilerplate filter for any scraping source
BAD_TOKENS = [
    'twitter', 'linkedin', 'facebook', 'google', 'instagram', 'privacy', 'terms', 'contact', 'about', 
    'cookies', 'login', 'signup', 'visit website', 'view', 'read', 'learn', 'more', 'policy', 'disclaimer',
    'careers', 'news', 'press', 'blog', 'support', 'help', 'search', 'menu', 'home', 'overview',
    'sustainability', 'climate', 'culture', 'foundation', 'equity', 'approach', 'credit', 'benefits',
    'staff', 'writers', 'feedback', 'recruit', 'bug', 'salary', 'salaries', 'tracker', 'teams', 'employers',
    'hiring now', 'open roles', 'job application', 'tech hubs', 'tech jobs', 'copyright', 'accessibility',
    'collection', 'contributor', 'statement', 'share', 'report', 'member', 'account', 'tools', 'resources'
]

def is_valid_company(name: str) -> bool:
    if not name or len(name) < 3: return False
    # Check for digit-benefits pattern like '38 Benefits'
    if re.search(r'\d+\s+benefits', name, re.IGNORECASE): return False
    # Check for navigation tokens
    name_check = name.lower()
    if any(tok in name_check for tok in BAD_TOKENS): return False
    # Real companies usually don't have too many slashes or dots unless it's a domain
    if '/' in name and 'http' not in name: return False
    return True

def fetch_industry_lists() -> List[Dict[str, Any]]:
    companies = []
    for url in config.INDUSTRY_LIST_URLS:
        try:
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for link in soup.find_all('a', href=True):
                    name = link.get_text(strip=True)
                    if is_valid_company(name):
                        companies.append({'name': name, 'domain': '', 'source': url})
        except: pass
    return companies

def scrape_vc_portfolios(vc_urls: List[str]) -> List[Dict[str, Any]]:
    companies = []
    for url in vc_urls:
        try:
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200: continue
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']
                name = link.get_text(strip=True)
                
                if is_valid_company(name) and 'http' in href:
                    domain = href.split('//')[-1].split('/')[0]
                    if '.' in domain and len(domain) > 3:
                        companies.append({'name': name, 'domain': domain, 'source': url})
        except: pass
    return companies

def score_company_worker(item: Dict[str, Any]):
    db = SessionLocal()
    try:
        # Check exists
        existing = db.query(Company).filter(Company.name == item['name']).first()
        if existing: return
        
        prompt = f"""
        Evaluate for Senior Enterprise Sales role fit (Payer/Healthcare/Fintech/CO Tech).
        Company: {item['name']} | Domain: {item['domain']}.
        
        Instructions:
        - If this name looks like a website navigation item or a generic word, set include to false.
        - High fit = Strategic buyers in Healthcare Payer, Managed Care, or Health Tech.
        
        Return JSON: {{"include": bool, "fit_score": int, "vertical": "string", "reasoning": "string"}}
        """
        response = call_llm(prompt, response_format="json")
        res = parse_json_from_llm(response)
        
        if res and res.get('include'):
            new_c = Company(
                name=item['name'],
                domain=item['domain'] if item['domain'] else None,
                vertical=res.get('vertical', 'other'),
                fit_score=res.get('fit_score', 0),
                raw_data=res
            )
            db.add(new_c)
            db.commit()
            logger.info(f"✨ Added: {new_c.name} ({new_c.vertical})")
    except Exception as e:
        logger.error(f"Error for {item['name']}: {e}")
    finally:
        db.close()

def build_universe():
    raw = fetch_industry_lists() + scrape_vc_portfolios(config.VC_PORTFOLIO_URLS)
    
    # Simple Dedupe
    unique = {c['name']: c for c in raw}.values()
    logger.info(f"Processing {len(unique)} candidate names after filters...")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Only process a batch to keep it clean
        executor.map(score_company_worker, list(unique)[:150])

if __name__ == "__main__":
    build_universe()
