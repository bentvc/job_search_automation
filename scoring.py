import logging
import re
import os
import yaml
from datetime import datetime
from typing import List, Optional, Dict, Any
from models import Company, Job, CompanySignal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_weights():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'scoring_weights.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {
        "vertical_fit": {"healthcare_payer": 70, "healthcare_general": 50, "fintech": 30, "enterprise_gtm": 25, "generic_saas": 10, "unaligned": 5},
        "lead_type_bonus": {"job_posting": 20, "signal_only": 10},
        "location_bonus": {"colorado_radius": 15},
        "signal_strength": {"funding": 20, "product_launch": 15, "leadership_change": 15, "hiring_spike": 10, "generic": 5}
    }

def score_lead(company: Optional[Company], job: Optional[Job] = None, signals: Optional[List[CompanySignal]] = None, weights: Optional[Dict[str, Any]] = None, return_breakdown: bool = False) -> Any:
    """
    Unified scoring function for both job_posting and signal_only leads.
    Returns: int (score) OR dict (if return_breakdown=True)
    """
    if not weights:
        weights = load_weights()
    
    breakdown = {
        "vertical_score": 0,
        "lead_type_score": 0,
        "location_score": 0,
        "signal_score": 0,
        "recency_score": 0,
        "role_adjustment": 0,
        "global_adjustment": 0,
        "final_score": 0
    }
    
    score = 0
    vertical = (company.vertical if company and company.vertical else "").lower()
    comp_name = (company.name if company and company.name else (job.company_name if job and job.company_name else ""))
    comp_name = comp_name.lower()

    # 0. Recency Score (for jobs)
    if job:
        r_weights = weights.get("recency_bonus", {})
        posted = job.date_posted or job.created_at
        if posted:
            hours_old = (datetime.utcnow() - posted).total_seconds() / 3600
            if hours_old <= 24:
                breakdown["recency_score"] = r_weights.get("lt_24h", 40)
            elif hours_old <= 72:
                breakdown["recency_score"] = r_weights.get("lt_72h", 25)
            elif hours_old <= 168: # 7 days
                breakdown["recency_score"] = r_weights.get("lt_1w", 10)
            elif hours_old <= 336: # 14 days
                breakdown['recency_score'] = r_weights.get("lt_2w", 0)
            else:
                breakdown["recency_score"] = r_weights.get("gt_2w", -20)
        score += breakdown["recency_score"]
    
    # 1. Vertical Fit
    v_weights = weights.get("vertical_fit", {})
    if any(k in vertical for k in ["payer", "plans", "managed care", "medicaid", "medicare", "benefits", "health plan"]):
        breakdown["vertical_score"] = v_weights.get("healthcare_payer", 70)
    elif any(k in vertical for k in ["health", "provider", "medical", "clinical", "care", "healthtech"]):
        breakdown["vertical_score"] = v_weights.get("healthcare_general", 50)
    elif any(k in vertical for k in ["fintech", "payments", "infrastructure", "banking", "billing"]):
        breakdown["vertical_score"] = v_weights.get("fintech", 30)
    elif any(k in vertical for k in ["devops", "software", "saas", "infrastructure"]):
        if job and any(k in job.title.lower() for k in ["vp", "cro", "director", "head"]):
            breakdown["vertical_score"] = v_weights.get("enterprise_gtm", 25)
        else:
            breakdown["vertical_score"] = v_weights.get("generic_saas", 10)
    else:
        breakdown["vertical_score"] = v_weights.get("unaligned", 5)
    
    score += breakdown["vertical_score"]

    # 2. Lead Type Bonus
    lt_weights = weights.get("lead_type_bonus", {})
    if job:
        breakdown["lead_type_score"] = lt_weights.get("job_posting", 20)
    else:
        breakdown["lead_type_score"] = lt_weights.get("signal_only", 10)
    
    score += breakdown["lead_type_score"]

    # 3. Locality Score
    loc_weights = weights.get("location_bonus", {})
    location = (company.hq_location if company else (job.location if job else "")) or ""
    location = location.lower()
    if any(k in location for k in ["colorado", "denver", "boulder", "co"]):
        breakdown["location_score"] = loc_weights.get("colorado_radius", 15)
    
    score += breakdown["location_score"]

    # 4. Signal strength
    if signals:
        ss_weights = weights.get("signal_strength", {})
        high_score = 0
        for sig in signals:
            txt = sig.signal_text.lower()
            if any(k in txt for k in ["funding", "raised", "round", "series"]):
                high_score = max(high_score, ss_weights.get("funding", 20))
            elif any(k in txt for k in ["launch", "product", "new"]):
                high_score = max(high_score, ss_weights.get("product_launch", 15))
            elif any(k in txt for k in ["cro", "ceo", "vp", "hire", "leader"]):
                high_score = max(high_score, ss_weights.get("leadership_change", 15))
            elif "hiring" in txt:
                high_score = max(high_score, ss_weights.get("hiring_spike", 10))
        breakdown["signal_score"] = high_score
        score += high_score

    # 5. Role-specific adjustments
    if job:
        title = job.title.lower()
        if any(k in title for k in ["vp", "director", "cro", "head", "strategic"]):
            breakdown["role_adjustment"] += 10
        
        ops_terms = ["operations", "enablement", "support", "admin", "specialist", "coordinator", "assistant"]
        if any(term in title for term in ops_terms) and not any(k in title for k in ["vp", "director", "head"]):
            # This is a cap, not just a penalty
            if (score + breakdown["role_adjustment"]) > 30:
                breakdown["role_adjustment"] = 30 - score

    score += breakdown["role_adjustment"]

    # 6. Global logo-based adjustments
    if any(k in comp_name for k in ["gitlab", "deputy"]):
        if score > 65:
            breakdown["global_adjustment"] = 65 - score
            score = 65

    final_val = max(0, min(100, int(score)))
    breakdown["final_score"] = final_val

    if return_breakdown:
        return breakdown
    return final_val

# Compatibility wrappers for old agents
def score_job_posting(company: Optional[Company], job: Job) -> int:
    return score_lead(company, job=job)

def score_signal_lead(company: Company, signals: List[CompanySignal]) -> int:
    return score_lead(company, signals=signals)
