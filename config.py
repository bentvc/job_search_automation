import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
APOLLO_API_KEY = os.getenv('APOLLO_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
LUX_API_KEY = os.getenv('LUX_API_KEY')
LUX_API_URL = os.getenv('LUX_API_URL')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
MINIMAX_API_KEY = os.getenv('MINIMAX_API_KEY')
Z_API_KEY = os.getenv('Z_API_KEY', '')  # z.ai backup

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./data/job_search.db')

# Pipeline Configuration
USE_V2_PIPELINE = os.getenv('USE_V2_PIPELINE', 'true').lower() == 'true'  # DeepSeek → Perplexity
ENABLE_EXPERIMENTAL_COUNCIL = os.getenv('ENABLE_EXPERIMENTAL_COUNCIL', 'false').lower() == 'true'  # Legacy multi-agent
ENABLE_AI_CONTENT_DETECTION = os.getenv('ENABLE_AI_CONTENT_DETECTION', 'true').lower() == 'true'  # Detect and remove AI-generated content markers
ENABLE_AGGRESSIVE_SCRAPING = os.getenv('ENABLE_AGGRESSIVE_SCRAPING', 'true').lower() == 'true'

# Signal Monitor Throttles (safe-mode)
SIGNAL_MONITOR_MAX_COMPANIES = os.getenv('SIGNAL_MONITOR_MAX_COMPANIES', '0')
SIGNAL_MONITOR_MAX_SIGNALS_PER_COMPANY = os.getenv('SIGNAL_MONITOR_MAX_SIGNALS_PER_COMPANY', '0')
SIGNAL_MONITOR_DISABLE_LLM = os.getenv('SIGNAL_MONITOR_DISABLE_LLM', 'false')

# Default Models (Cost-Optimized Hierarchy)
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20240620"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat"
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.1"  # M2.1 via Anthropic API
DEFAULT_Z_MODEL = "z-1"  # z.ai model

# Apollo Target Titles
APOLLO_PRIMARY_GTM_TITLES = [
    "Chief Revenue Officer", "CRO", "Chief Commercial Officer", "CCO", 
    "Chief Growth Officer", "CGO", "VP Sales", "SVP Sales", "Head of Sales", 
    "VP Revenue", "VP Business Development", "VP Partnerships", 
    "VP Customer Success", "VP Enterprise Sales", "Director of Sales"
]

APOLLO_EARLY_STAGE_TITLES = [
    "CEO", "Founder", "Co-Founder", "President", "COO"
]

APOLLO_DOMAIN_GTM_TITLES = [
    "VP Payer Partnerships", "VP Provider Partnerships", "VP Healthcare", 
    "Head of Payer Strategy", "VP Market Engagement"
]

APOLLO_TARGET_TITLES = APOLLO_PRIMARY_GTM_TITLES + APOLLO_EARLY_STAGE_TITLES + APOLLO_DOMAIN_GTM_TITLES

# Candidate Profile
USER_PROFILE_SUMMARY = """
Senior enterprise sales professional with 15+ years in payer/health plan sales. 
Built and led $90M+ books of business selling to Medicaid, Medicare Advantage, and commercial health plans. 
Closed multiple 7-figure, multi-year contracts. Deep expertise in utilization management, payment integrity, 
network, risk adjustment, value-based care. Also experienced in general enterprise SaaS and fintech with 
complex, long-cycle deals. 
PRIORITY: Revenue-generating roles ONLY (VP Sales, CRO, Head of Sales, Strategic AE).
NOT INTERESTED: Sales Operations, Enablement, Finance, or Support roles. 
Based in Denver, CO; open to remote US roles.
"""

# Job Search Settings (HIGH VOLUME)
JOBSPY_QUERIES = [
    '"VP Sales" OR "SVP Sales" OR "Head of Sales" OR "CRO" healthtech payer',
    '"VP" OR "Head of" Medicaid Medicare "health plan"',
    '"Enterprise Account Executive" payer "health plan"',
    '"Strategic Account Executive" Medicaid "Medicare Advantage"',
    '"VP Sales" OR "SVP Sales" OR "Head of Sales" OR "CRO"',
    '"Enterprise Account Executive" OR "Strategic Account Executive"',
    '"VP Sales" fintech payments B2B',
    '"VP Sales" Denver Colorado',
    '"Head of Growth" healthcare sales',
    'enterprise sales healthcare',
    'senior account executive remote healthcare',
    'director sales health technology',
    'payer sales',
    'managed care sales'
]

# JobSpy Multi-Site Configuration (VOLUME BOOST)
JOBSPY_SITES = ["linkedin", "indeed", "ziprecruiter", "glassdoor"]
JOBSPY_RESULTS_PER_QUERY = 100  # Up from 10

# Greenhouse/Lever Direct ATS Targets
GREENHOUSE_TARGETS = [
    "humana", "cigna", "optum", "anthem", "molina", "centene",
    "oscar-health", "clover-health", "devoted-health", "bright-health",
    "collectivehealth", "gravie", "bind-benefits", "sidecar-health",
    "rightway-healthcare", "league", "accolade",
    "flatiron-health", "tempus", "komodohealth", "healthverity"
]

# VC Portfolio Monitoring
VC_PORTFOLIO_URLS = [
    'https://oakhc.com/portfolio/',
    'https://a16z.com/portfolio/',
    'https://www.generalatlantic.com/portfolio/',
    'https://www.sequoiacap.com/our-companies/',
    'https://www.bvp.com/portfolio',
    'https://www.accel.com/portfolio',
    'https://www.insightpartners.com/portfolio/',
]

# Industry Lists
INDUSTRY_LIST_URLS = [
    'https://rockhealth.com/reports/funding-database/',
    'https://builtin.com/companies?location=colorado',
]

# Mailgun Configuration
MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY')
MAILGUN_DOMAIN = os.getenv('MAILGUN_DOMAIN', 'mg.freeboard-advisory.com')
DEFAULT_BCC_EMAIL = 'bent@freeboard-advisory.com'
MAILGUN_DOMAIN_FREEBOARD = os.getenv('MAILGUN_DOMAIN_FREEBOARD', MAILGUN_DOMAIN)
MAILGUN_DOMAIN_CHRISTIANSEN = os.getenv('MAILGUN_DOMAIN_CHRISTIANSEN', MAILGUN_DOMAIN)

# Scoring & Enrichment
MIN_OVERALL_SCORE_TO_SCRAPE_HM = 60
TIER_1_THRESHOLD = 80
MAX_CONTACTS_PER_COMPANY = 5

# Growth Signal Scoring Weights (for explosive growth, escape velocity, profitability)
GROWTH_SIGNAL_WEIGHTS = {
    'funding_round': 25,
    'hiring_spike': 20,
    'employee_growth': 15,
    'profitability_signal': 30,
    'leadership_change': 10,
    'partnership_announcement': 10,
    'award_recognition': 5,
}

# Company Fit Scoring Criteria (prioritize explosive growth companies)
COMPANY_FIT_CRITERIA = {
    'explosive_growth': {
        'employee_growth_90d': 20,
        'revenue_growth': 15,
        'funding_recent': 10,
    },
    'escape_velocity': {
        'series_b_or_later': 15,
        'profitable': 20,
        'market_leader': 10,
    },
    'profitability': {
        'profitable': 25,
        'positive_cash_flow': 15,
        'path_to_profitability': 10,
    }
}
