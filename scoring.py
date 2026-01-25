import logging
import re
from typing import List, Optional
from models import Company, Job, CompanySignal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def score_job_posting(company: Optional[Company], job: Job) -> int:
    """
    Score a job posting based on vertical fit and role relevance.
    Prioritizes Healthcare/Fintech logos over horizontal SaaS.
    """
    score = 50  # Base score
    
    # 1. Vertical Fit (Strong Weight)
    healthcare_keywords = ["payer", "health plan", "healthtech", "provider", "benefits", "care management", "medicaid", "medicare", "vbc", "value-based care"]
    fintech_keywords = ["fintech", "payments", "infrastructure", "banking", "billing"]
    
    vertical = (company.vertical if company else "").lower()
    comp_name = (company.name if company else (job.company_name or "")).lower()
    job_title = (job.title or "").lower()
    job_desc = (job.description or "").lower()
    
    is_healthcare = any(k in vertical for k in healthcare_keywords) or any(k in comp_name for k in ["evolent", "molina", "gravie", "experity", "unitedhealthcare", "aetna", "cigna", "humana"])
    is_fintech = any(k in vertical for k in fintech_keywords)
    
    if is_healthcare:
        score += 30
        logger.info(f"Healthcare bonus applied for {job.company_name}")
    elif is_fintech:
        score += 15
        logger.info(f"Fintech bonus applied for {job.company_name}")
    
    # 2. Role Description Keywords
    payer_keywords = ["medicaid", "medicare advantage", "value-based care", "utilization management", "prior authorization", "payment integrity", "network", "access", "risk adjustment"]
    if any(k in job_desc for k in payer_keywords) or any(k in job_title for k in payer_keywords):
        score += 20
        logger.info(f"Payer/VBC keyword bonus applied for {job.title}")

    # 3. Role Seniority & Enterprise Focus
    enterprise_keywords = ["vp", "director", "cro", "head of", "enterprise", "strategic", "ae", "account executive"]
    if any(k in job_title for k in enterprise_keywords):
        score += 10
    
    # 4. Deprioritize non-core horizontal SaaS
    horizontal_keywords = ["devops", "plg", "devrel", "developer relations", "horizontal saas", "gitlab"]
    if any(k in vertical for k in horizontal_keywords) or any(k in job_title for k in horizontal_keywords) or "gitlab" in comp_name:
        if not is_healthcare:  # Only deprioritize if not also healthcare (unlikely but safe)
            score -= 20
            logger.info(f"Horizontal SaaS deprioritization for {job.company_name}")

    # 5. Hard Rejections (inherited from old logic but simplified)
    ops_terms = ["operations", "enablement", "support", "admin", "specialist", "coordinator", "assistant"]
    if any(term in job_title for term in ops_terms) and not any(k in job_title for k in ["vp", "director", "head"]):
        score = min(score, 30)
        
    return max(0, min(100, int(score)))

def score_signal_lead(company: Company, signals: List[CompanySignal]) -> int:
    """
    Score a signal-based lead regardless of vertical, bias toward signal strength.
    """
    score = 40  # Lower base for signals
    
    if not signals:
        return 0
        
    highest_signal_score = max([s.score for s in signals]) if signals else 0
    score += highest_signal_score * 0.5 # 50% of signal strength
    
    # 1. Signal Type Bonuses
    recent_signals = [s.signal_type.lower() for s in signals]
    if any(k in recent_signals for k in ["funding", "investment"]):
        score += 15
    if any(k in recent_signals for k in ["launch", "product", "expansion"]):
        score += 15
    if any(k in recent_signals for k in ["leadership", "hiring_spike", "cro", "ceo"]):
        score += 10
        
    # 2. Secondary Vertical Adjustment
    healthcare_keywords = ["payer", "health plan", "healthtech", "provider", "benefits"]
    vertical = (company.vertical or "").lower()
    if any(k in vertical for k in healthcare_keywords):
        score += 10
        
    return max(0, min(100, int(score)))
