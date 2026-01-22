"""
BONUS SCRAPER #7: RSS Feed Aggregator for Funding News
Monitors TechCrunch, Fierce Healthcare, and healthcare funding newsletters
Expected: 50-100+ fresh funding announcements per week
"""
import logging
from database import SessionLocal
from models import Company, CompanySignal
import feedparser
import uuid
from datetime import datetime, timedelta
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RSS Feed Sources
RSS_FEEDS = {
    'techcrunch_healthcare': 'https://techcrunch.com/tag/healthcare/feed/',
    'techcrunch_funding': 'https://techcrunch.com/tag/funding/feed/',
    'fierce_healthcare': 'https://www.fiercehealthcare.com/rss/xml',
    'healthcare_finance': 'https://www.healthcarefinancenews.com/feed',
    'mobihealthnews': 'https://www.mobihealthnews.com/feed'
}

def extract_funding_info(text):
    """Extract funding amount and company from article text"""
    # Look for funding patterns
    funding_patterns = [
        r'raised \$?([\d.]+[MBK])',
        r'\$?([\d.]+[MBK]) in funding',
        r'\$?([\d.]+[MBK]) Series [A-Z]',
        r'closes \$?([\d.]+[MBK])'
    ]
    
    funding = None
    for pattern in funding_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            funding = f"${match.group(1)}"
            break
    
    # Extract company name (usually in first part of title)
    company_match = re.match(r'^([^:,\-]+)', text)
    company = company_match.group(1).strip() if company_match else None
    
    return company, funding

def scrape_rss_feed(feed_url, feed_name):
    """Scrape a single RSS feed"""
    try:
        logger.info(f"📡 Fetching {feed_name}...")
        feed = feedparser.parse(feed_url)
        
        signals = []
        cutoff_date = datetime.now() - timedelta(days=30)  # Only last 30 days
        
        for entry in feed.entries[:50]:  # Last 50 entries
            try:
                title = entry.get('title', '')
                link = entry.get('link', '')
                published = entry.get('published_parsed')
                summary = entry.get('summary', '')
                
                # Check if it's recent
                if published:
                    pub_date = datetime(*published[:6])
                    if pub_date < cutoff_date:
                        continue
                else:
                    pub_date = datetime.now()
                
                # Check if it's funding-related
                content = f"{title} {summary}".lower()
                if not any(keyword in content for keyword in ['raised', 'funding', 'series', 'investment', 'venture', 'closes']):
                    continue
                
                # Extract company and funding info
                company_name, funding = extract_funding_info(title)
                
                if not company_name:
                    continue
                
                signals.append({
                    'company_name': company_name,
                    'funding': funding,
                    'title': title,
                    'url': link,
                    'published': pub_date,
                    'source': feed_name
                })
                
            except Exception as e:
                logger.debug(f"Error parsing RSS entry: {e}")
                continue
        
        logger.info(f"✅ {feed_name}: Found {len(signals)} funding signals")
        return signals
        
    except Exception as e:
        logger.error(f"Error scraping RSS feed {feed_name}: {e}")
        return []

def store_funding_signals(signals_data):
    """Store funding signals and create/update companies"""
    db = SessionLocal()
    try:
        companies_created = 0
        signals_created = 0
        
        for signal_data in signals_data:
            # Find or create company
            company = db.query(Company).filter(Company.name.ilike(f"%{signal_data['company_name']}%")).first()
            
            if not company:
                # Create new company
                company = Company(
                    id=str(uuid.uuid4()),
                    name=signal_data['company_name'],
                    domain=None,
                    vertical='healthcare',
                    fit_score=85,  # High score for funded companies
                    monitoring_status='active',
                    raw_data=signal_data
                )
                db.add(company)
                companies_created += 1
            
            # Check if signal already exists
            existing_signal = db.query(CompanySignal).filter(
                CompanySignal.company_id == company.id,
                CompanySignal.source_url == signal_data['url']
            ).first()
            
            if not existing_signal:
                # Create funding signal
                signal_text = signal_data['title']
                if signal_data['funding']:
                    signal_text = f"Raised {signal_data['funding']}: {signal_data['title']}"
                
                new_signal = CompanySignal(
                    id=str(uuid.uuid4()),
                    company_id=company.id,
                    signal_type='funding',
                    signal_date=signal_data['published'],
                    signal_text=signal_text,
                    score=90,  # Very high urgency for funding news
                    source_url=signal_data['url']
                )
                db.add(new_signal)
                signals_created += 1
        
        db.commit()
        logger.info(f"💾 Created {companies_created} companies, {signals_created} funding signals")
        return companies_created, signals_created
        
    finally:
        db.close()

def run_rss_aggregator():
    """Main RSS feed aggregator"""
    logger.info("📰 Launching RSS Funding News Aggregator")
    
    all_signals = []
    
    for feed_name, feed_url in RSS_FEEDS.items():
        signals = scrape_rss_feed(feed_url, feed_name)
        all_signals.extend(signals)
    
    logger.info(f"📊 Total signals found: {len(all_signals)}")
    
    companies_created, signals_created = store_funding_signals(all_signals)
    
    logger.info(f"✅ RSS Aggregator Complete: {companies_created} new companies, {signals_created} funding signals")
    return companies_created, signals_created

if __name__ == "__main__":
    run_rss_aggregator()
