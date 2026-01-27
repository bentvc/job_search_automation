import logging
import re
import os
import yaml
from datetime import datetime
from typing import List, Optional, Dict, Any
from models import Company, Job, CompanySignal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Role-fit keywords for healthcare verticals (revenue-role ONLY)
REVENUE_ROLE_KEYWORDS = [
    "vp sales", "vp of sales", "svp sales", "chief revenue", "cro", "head of sales",
    "director of sales", "head of growth", "vp revenue", "vp business development",
    "strategic account", "enterprise account", "regional vice president",
    "vp,", "director,", "head of", "head of revenue",
]
REJECT_ROLE_KEYWORDS = [
    "sales ops", "sales operations", "enablement", "revops", "revenue operations",
    "customer success", " csm", "implementation manager", "implementation consultant",
    "support specialist", "sales admin", "operations coordinator",
]

def load_weights():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'scoring_weights.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {
        "vertical_fit": {"healthcare_payer": 70, "healthcare_general": 50, "fintech": 30, "enterprise_gtm": 25, "generic_saas": 10, "unaligned": 5},
        "lead_type_bonus": {"job_posting": 20, "signal_only": 10},
        "location_bonus": {"colorado_radius": 15},
        "signal_strength": {"funding": 20, "product_launch": 15, "leadership_change": 15, "new_role_announcement": 22, "new_role_posting": 18, "hiring_spike": 10, "generic": 5},
        "signal_strength_cap": 35,
        "recency_multiplier": {"lt_24h": 1.15, "lt_72h": 1.10, "lt_1w": 1.05, "lt_2w": 1.0, "gt_2w": 0.85},
        "role_fit_healthcare": {"revenue_bonus": 10, "reject_penalty": -35},
    }

def score_lead(company: Optional[Company], job: Optional[Job] = None, signals: Optional[List[CompanySignal]] = None, weights: Optional[Dict[str, Any]] = None, return_breakdown: bool = False) -> Any:
    """
    Unified scoring: fit = vertical + lead_type + signal + role. Recency is a multiplier.
    Location is priority_boost only (callers add to priority_score). Hard reject for
    healthcare + Ops/Enablement/Support in job title.
    """
    if not weights:
        weights = load_weights()
    
    breakdown = {
        "vertical_score": 0,
        "lead_type_score": 0,
        "location_score": 0,
        "priority_boost": 0,  # add to priority_score, not fit
        "signal_score": 0,
        "recency_multiplier": 1.0,
        "role_adjustment": 0,
        "global_adjustment": 0,
        "base_score": 0,
        "final_score": 0,
    }
    
    vertical = (company.vertical if company and company.vertical else "").lower()
    comp_name = (company.name if company and company.name else (job.company_name if job and job.company_name else ""))
    comp_name = comp_name.lower()
    is_healthcare_payer = any(k in vertical for k in ["payer", "plans", "managed care", "medicaid", "medicare", "benefits", "health plan"])
    is_healthcare_general = any(k in vertical for k in ["health", "provider", "medical", "clinical", "care", "healthtech"])
    is_healthcare = is_healthcare_payer or is_healthcare_general

    # Hard reject: healthcare + any Ops/Enablement/Support in job title → fit = 0
    if job and is_healthcare:
        title = (job.title or "").lower()
        if any(r in title for r in REJECT_ROLE_KEYWORDS):
            breakdown["final_score"] = 0
            breakdown["priority_boost"] = weights.get("location_bonus", {}).get("colorado_radius", 15) if any(k in ((company.hq_location or "") + (job.location or "")).lower() for k in ["colorado", "denver", "boulder", "co"]) else 0
            if return_breakdown:
                return breakdown
            return 0

    # 1. Vertical Fit
    v_weights = weights.get("vertical_fit", {})
    if is_healthcare_payer:
        breakdown["vertical_score"] = v_weights.get("healthcare_payer", 70)
    elif is_healthcare_general:
        breakdown["vertical_score"] = v_weights.get("healthcare_general", 50)
    elif any(k in vertical for k in ["fintech", "payments", "infrastructure", "banking", "billing"]):
        breakdown["vertical_score"] = v_weights.get("fintech", 30)
    elif any(k in vertical for k in ["devops", "software", "saas", "infrastructure"]):
        if job and any(k in (job.title or "").lower() for k in ["vp", "cro", "director", "head"]):
            breakdown["vertical_score"] = v_weights.get("enterprise_gtm", 25)
        else:
            breakdown["vertical_score"] = v_weights.get("generic_saas", 10)
    else:
        breakdown["vertical_score"] = v_weights.get("unaligned", 5)
    
    base = breakdown["vertical_score"]

    # 2. Lead Type
    lt_weights = weights.get("lead_type_bonus", {})
    breakdown["lead_type_score"] = lt_weights.get("job_posting", 20) if job else lt_weights.get("signal_only", 10)
    base += breakdown["lead_type_score"]

    # 3. Location → priority_boost only (not added to fit)
    loc_weights = weights.get("location_bonus", {})
    location = (company.hq_location if company else (job.location if job else "")) or ""
    location = location.lower()
    if any(k in location for k in ["colorado", "denver", "boulder", "co"]):
        breakdown["location_score"] = breakdown["priority_boost"] = loc_weights.get("colorado_radius", 15)
    # do not add to base

    # 4. Signal strength (stack with cap)
    if signals:
        ss_weights = weights.get("signal_strength", {})
        bucket_scores: Dict[str, int] = {}
        for sig in signals:
            txt = (sig.signal_text or "").lower()
            if "new role posting" in txt:
                bucket_scores["new_role_posting"] = max(bucket_scores.get("new_role_posting", 0), ss_weights.get("new_role_posting", 18))
            elif "new role announcement" in txt or "new role" in txt:
                bucket_scores["new_role_announcement"] = max(bucket_scores.get("new_role_announcement", 0), ss_weights.get("new_role_announcement", 22))
            elif any(k in txt for k in ["funding", "raised", "round", "series"]):
                bucket_scores["funding"] = max(bucket_scores.get("funding", 0), ss_weights.get("funding", 20))
            elif any(k in txt for k in ["launch", "product", "new product"]):
                bucket_scores["product_launch"] = max(bucket_scores.get("product_launch", 0), ss_weights.get("product_launch", 15))
            elif any(k in txt for k in ["cro", "ceo", "vp", "hire", "leader", "chief revenue", "chief commercial"]):
                bucket_scores["leadership_change"] = max(bucket_scores.get("leadership_change", 0), ss_weights.get("leadership_change", 15))
            elif "hiring" in txt:
                bucket_scores["hiring_spike"] = max(bucket_scores.get("hiring_spike", 0), ss_weights.get("hiring_spike", 10))
        cap = int(weights.get("signal_strength_cap", 35))
        breakdown["signal_score"] = min(sum(bucket_scores.values()), cap)
        base += breakdown["signal_score"]

    # 5. Role adjustments
    if job:
        title = (job.title or "").lower()
        rf = weights.get("role_fit_healthcare", {})
        revenue_bonus = rf.get("revenue_bonus", 10)
        reject_penalty = rf.get("reject_penalty", -35)
        if is_healthcare:
            if any(r in title for r in REVENUE_ROLE_KEYWORDS):
                breakdown["role_adjustment"] = revenue_bonus
            # reject case already handled above
        else:
            if any(k in title for k in ["vp", "director", "cro", "head", "strategic"]):
                breakdown["role_adjustment"] = 10
            ops_terms = ["operations", "enablement", "support", "admin", "specialist", "coordinator", "assistant"]
            if any(term in title for term in ops_terms) and not any(k in title for k in ["vp", "director", "head"]):
                if base + breakdown["role_adjustment"] > 30:
                    breakdown["role_adjustment"] = 30 - base
    base += breakdown["role_adjustment"]

    # 6. Recency as multiplier (not additive)
    recency_mult = 1.0
    if job:
        r_mult = weights.get("recency_multiplier", {})
        posted = job.date_posted or job.created_at
        if posted:
            hours_old = (datetime.utcnow() - posted).total_seconds() / 3600
            if hours_old <= 24:
                recency_mult = r_mult.get("lt_24h", 1.15)
            elif hours_old <= 72:
                recency_mult = r_mult.get("lt_72h", 1.10)
            elif hours_old <= 168:
                recency_mult = r_mult.get("lt_1w", 1.05)
            elif hours_old <= 336:
                recency_mult = r_mult.get("lt_2w", 1.0)
            else:
                recency_mult = r_mult.get("gt_2w", 0.85)
    breakdown["recency_multiplier"] = recency_mult
    breakdown["base_score"] = base
    score = base * recency_mult

    # 7. Global adjustments
    if any(k in comp_name for k in ["gitlab", "deputy"]) and score > 65:
        breakdown["global_adjustment"] = 65 - score
        score = 65

    final_val = max(0, min(100, int(round(score))))
    breakdown["final_score"] = final_val

    if return_breakdown:
        return breakdown
    return final_val

# Compatibility wrappers for old agents
def score_job_posting(company: Optional[Company], job: Job) -> int:
    return score_lead(company, job=job)

def score_signal_lead(company: Company, signals: List[CompanySignal]) -> int:
    return score_lead(company, signals=signals)


def score_candidate(company_name: str, vertical: str, context: str, weights: Optional[Dict[str, Any]] = None) -> int:
    """
    Score a discovery candidate from name/vertical/context only. No Company/Job/Signals.
    Used by Agent 6 Stage 2 (Sieve). Returns 0–100; 0 if context implies non–revenue-role.
    """
    if not weights:
        weights = load_weights()
    text = f"{company_name} {vertical} {context}".lower()
    if any(r in text for r in REJECT_ROLE_KEYWORDS):
        return 0
    v_weights = weights.get("vertical_fit", {})
    vert_low = (vertical or "").lower()
    ctx_low = (context or "").lower()
    if any((k in vert_low) or (k in ctx_low) for k in ["payer", "plans", "managed care", "medicaid", "medicare", "benefits", "health plan"]):
        base = v_weights.get("healthcare_payer", 70)
    elif any((k in vert_low) or (k in ctx_low) for k in ["health", "provider", "medical", "clinical", "care", "healthtech"]):
        base = v_weights.get("healthcare_general", 50)
    elif any((k in vert_low) or (k in ctx_low) for k in ["fintech", "payments", "insurance", "banking", "billing"]):
        base = v_weights.get("fintech", 30)
    else:
        base = v_weights.get("unaligned", 5)
    base += weights.get("lead_type_bonus", {}).get("signal_only", 10)

    # News-intent weighting: real GTM events float, passive mentions sink
    INTENT_BONUS = {
        "launch": 15, "expansion": 15, "new product": 20, "funding": 20, "series": 20,
        "hiring": 10, "vp sales": 20, "cro": 25, "chief revenue": 25, "raised": 15, "raises": 15,
    }
    intent_score = 0
    for k, v in INTENT_BONUS.items():
        if k in ctx_low:
            intent_score = max(intent_score, v)
    base += intent_score
    return max(0, min(100, int(base)))
