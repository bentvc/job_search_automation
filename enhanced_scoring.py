"""
Enhanced company scoring that prioritizes explosive growth, escape velocity, and profitability.
"""
import logging
from database import SessionLocal
from models import Company, CompanySignal
import config
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_growth_score(company: Company) -> int:
    """
    Calculate growth score based on signals indicating explosive growth.
    Returns: 0-100 score
    """
    db = SessionLocal()
    try:
        # Get recent signals (last 90 days)
        cutoff_date = datetime.utcnow() - timedelta(days=90)
        recent_signals = db.query(CompanySignal).filter(
            CompanySignal.company_id == company.id,
            CompanySignal.signal_date >= cutoff_date
        ).all()
        
        score = 0
        
        # Check for explosive growth indicators
        signal_types = {}
        for signal in recent_signals:
            signal_types[signal.signal_type] = signal_types.get(signal.signal_type, 0) + 1
        
        # Funding rounds (indicates growth capital)
        if signal_types.get('funding', 0) > 0:
            score += config.GROWTH_SIGNAL_WEIGHTS.get('funding_round', 25)
        
        # Hiring spikes (indicates scaling)
        hiring_signals = [s for s in recent_signals if 'hiring' in s.signal_type.lower() or 'job' in s.signal_type.lower()]
        if len(hiring_signals) >= 3:  # 3+ hiring signals = spike
            score += config.GROWTH_SIGNAL_WEIGHTS.get('hiring_spike', 20)
        
        # Employee growth (if we have this data)
        if company.employee_count:
            # Check if we have historical data (would need to track this)
            # For now, use signal_score_30d as proxy
            if company.signal_score_30d and company.signal_score_30d > 70:
                score += config.GROWTH_SIGNAL_WEIGHTS.get('employee_growth', 15)
        
        # Profitability signals
        if company.profitability_signal:
            profitability_lower = company.profitability_signal.lower()
            if any(term in profitability_lower for term in ['profitable', 'cash flow positive', 'break-even']):
                score += config.GROWTH_SIGNAL_WEIGHTS.get('profitability_signal', 30)
        
        # Leadership changes (new CRO/VP Sales = hiring intent)
        leadership_signals = [s for s in recent_signals if 'leadership' in s.signal_type.lower() or 'executive' in s.signal_type.lower()]
        if leadership_signals:
            score += config.GROWTH_SIGNAL_WEIGHTS.get('leadership_change', 10)
        
        # Cap at 100
        return min(score, 100)
        
    finally:
        db.close()

def calculate_escape_velocity_score(company: Company) -> int:
    """
    Calculate escape velocity score - companies that have reached product-market fit
    and are scaling sustainably.
    Returns: 0-100 score
    """
    score = 0
    
    # Series B or later = proven model
    if company.stage:
        stage_lower = company.stage.lower()
        if any(term in stage_lower for term in ['series b', 'series c', 'series d', 'series e', 'growth', 'late stage']):
            score += config.COMPANY_FIT_CRITERIA['escape_velocity'].get('series_b_or_later', 15)
    
    # Profitable = sustainable
    if company.profitability_signal:
        profitability_lower = company.profitability_signal.lower()
        if any(term in profitability_lower for term in ['profitable', 'cash flow positive']):
            score += config.COMPANY_FIT_CRITERIA['escape_velocity'].get('profitable', 20)
    
    # Employee count as proxy for scale (100+ employees = escape velocity)
    if company.employee_count and company.employee_count >= 100:
        score += 10
    
    # Funding total as proxy (raised $20M+ = escape velocity)
    if company.funding_total and company.funding_total >= 20000000:
        score += 10
    
    return min(score, 100)

def calculate_profitability_score(company: Company) -> int:
    """
    Calculate profitability score - prioritize companies that are profitable or on path.
    Returns: 0-100 score
    """
    score = 0
    
    if company.profitability_signal:
        profitability_lower = company.profitability_signal.lower()
        
        # Direct profitability
        if any(term in profitability_lower for term in ['profitable', 'profitable company', 'generating profit']):
            score += config.COMPANY_FIT_CRITERIA['profitability'].get('profitable', 25)
        
        # Cash flow positive
        if any(term in profitability_lower for term in ['cash flow positive', 'positive cash flow', 'cash positive']):
            score += config.COMPANY_FIT_CRITERIA['profitability'].get('positive_cash_flow', 15)
        
        # Path to profitability
        if any(term in profitability_lower for term in ['path to profitability', 'near profitability', 'approaching profitability']):
            score += config.COMPANY_FIT_CRITERIA['profitability'].get('path_to_profitability', 10)
    
    # Stage-based inference (late stage = more likely profitable)
    if company.stage:
        stage_lower = company.stage.lower()
        if any(term in stage_lower for term in ['series c', 'series d', 'series e', 'growth', 'late stage']):
            score += 15
    
    return min(score, 100)

def recalculate_company_fit_score(company_id: str):
    """
    Recalculate fit score for a company incorporating growth, escape velocity, and profitability.
    """
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return
        
        # Base fit score (existing)
        base_score = company.fit_score or 50
        
        # Calculate component scores
        growth_score = calculate_growth_score(company)
        escape_velocity_score = calculate_escape_velocity_score(company)
        profitability_score = calculate_profitability_score(company)
        
        # Weighted combination (prioritize explosive growth + profitability)
        # Formula: 40% base + 30% growth + 20% profitability + 10% escape velocity
        weighted_score = (
            base_score * 0.4 +
            growth_score * 0.3 +
            profitability_score * 0.2 +
            escape_velocity_score * 0.1
        )
        
        # Boost for companies with all three signals
        if growth_score >= 70 and profitability_score >= 50 and escape_velocity_score >= 50:
            weighted_score = min(weighted_score * 1.15, 100)  # 15% boost
        
        # Update company
        company.fit_score = int(weighted_score)
        db.commit()
        
        logger.info(f"✅ Recalculated fit score for {company.name}: {int(weighted_score)} (growth: {growth_score}, profit: {profitability_score}, escape: {escape_velocity_score})")
        
    finally:
        db.close()

def batch_recalculate_fit_scores():
    """
    Recalculate fit scores for all active companies.
    """
    db = SessionLocal()
    try:
        companies = db.query(Company).filter(Company.monitoring_status == 'active').all()
        logger.info(f"Recalculating fit scores for {len(companies)} companies...")
        
        for company in companies:
            recalculate_company_fit_score(company.id)
        
        logger.info("✅ Batch recalculation complete")
    finally:
        db.close()

if __name__ == "__main__":
    batch_recalculate_fit_scores()
