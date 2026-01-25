import logging
from database import SessionLocal
from models import Job, ProactiveOutreach, Company, Contact
import uuid
from datetime import datetime
from utils import call_llm, parse_json_from_llm
import config
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# USER PROFILE
CANDIDATE_PROFILE = """
- Senior Commercial Executive (VP/SVP/CRO level) with 15+ years in Healthcare/Digital Health.
- Track record: Scaled revenue from $0 to $50M+, built high-performing sales teams.
- Expertise: Payer/Provider markets, Value-Based Care, Enterprise SaaS sales.
- Style: Consultative, strategic, player-coach.
"""

def identify_penetration_wedge(company, contact, job=None, signal=None, use_local=True):
    """
    Identify the best account penetration wedge.
    
    Args:
        use_local: If True, use local DeepSeek-R1 (free, slower). If False, use MiniMax API (fast, cheap).
    
    Returns: wedge_type (str), wedge_rationale (str)
    """
    job_context = f"Role: {job.title}" if job else "Proactive Outreach"
    signal_text = signal if signal else "High-fit target"
    
    prompt = f"""
    Analyze this outreach opportunity and identify the BEST account penetration wedge.
    
    Company: {company.name} ({company.vertical})
    Contact: {contact.name} ({contact.title})
    Context: {job_context}
    Signal: {signal_text}
    
    Candidate Profile: {CANDIDATE_PROFILE}
    
    Identify the PRIMARY penetration wedge from these options:
    1. **Direct Role Match**: Applying for specific posted role
    2. **Growth Signal**: Recent funding, expansion, hiring spike
    3. **Domain Expertise**: Deep payer/healthcare experience match
    4. **Stage Fit**: Company at inflection point needing sales leadership
    5. **Competitive Angle**: Company competing in space where candidate has wins
    6. **Relationship Leverage**: Shared connections, mutual contacts
    
    Return JSON:
    {{
        "wedge_type": "string (one of the 6 options)",
        "wedge_rationale": "2-3 sentence explanation of why this wedge is strongest"
    }}
    """
    
    try:
        if use_local:
            # Use local DeepSeek-R1 (free, for batch processing)
            from ollama_client import call_ollama
            resp = call_ollama(prompt, model="deepseek-r1:32b", response_format="json")
        else:
            # Use MiniMax API (fast, for real-time alerts)
            resp = call_llm(prompt, response_format="json", forced_provider="minimax")
        
        result = parse_json_from_llm(resp)
        return result.get("wedge_type", "Domain Expertise"), result.get("wedge_rationale", "")
    except Exception as e:
        logger.warning(f"Wedge identification failed: {e}, using default")
        return "Domain Expertise", "Strong healthcare/payer domain match"

def generate_outreach_content(company, contact, job=None, signal=None, use_local=True, verify=True):
    """
    Enhanced Council of Agents with penetration wedge discrimination, optimized LLM usage,
    and optional verification to prevent hallucinations.
    
    Args:
        use_local: If True, use local DeepSeek-R1 (free, for overnight batch).
                   If False, use MiniMax API (fast, for real-time alerts).
        verify: If True, use Perplexity to fact-check claims (recommended).
    """
    if not contact: return None
    
    # Step 0: Verify company vertical (optional but recommended)
    company_vertical_verified = company.vertical or "unknown"
    if verify:
        try:
            from verification_agent import get_company_vertical
            vertical_info = get_company_vertical(company.name)
            if vertical_info['confidence'] > 70:
                company_vertical_verified = vertical_info['primary_vertical']
                logger.info(f"Verified {company.name} vertical: {company_vertical_verified} (was: {company.vertical})")
        except Exception as e:
            logger.warning(f"Vertical verification skipped: {e}")
    
    # Step 1: Identify penetration wedge
    wedge_type, wedge_rationale = identify_penetration_wedge(company, contact, job, signal, use_local=use_local)
    
    # Context
    job_context = ""
    if job:
        job_context = f"Applying for Role: {job.title}\nJob URL: {job.url}\n"
    
    # Step 2: Council analysis with wedge-specific angles AND vertical awareness
    prompt = f"""
    You are the "Council of Agents" for an executive job seeker. Three personas collaborate:
    1. **The Strategist**: Analytical, focuses on business value, ROI, competitor weakness.
    2. **The Dealmaker**: Direct, bold, focuses on getting the meeting and the close.
    3. **The Writer**: Polished, human, concise, warm but professional.
    
    **YOUR GOAL**: Secure a conversation with {contact.name}, who is the {contact.title} at {company.name}.
    
    **YOUR PROFILE**:
    {CANDIDATE_PROFILE}
    
    **TARGET CONTEXT**:
    Company: {company.name}
    Company's Actual Vertical: {company_vertical_verified}
    {job_context}
    Signal/Trigger: {signal if signal else 'Strategic Universe Target'}
    
    **PENETRATION WEDGE**: {wedge_type}
    **WEDGE RATIONALE**: {wedge_rationale}
    
    **CRITICAL INSTRUCTIONS - AVOID HALLUCINATIONS**:
    1. ONLY reference the candidate's healthcare/payer experience if {company.name} ACTUALLY operates in healthcare/payer vertical
    2. If {company.name} is NOT healthcare (e.g., DevOps, cybersecurity, SaaS), focus on:
       - General enterprise sales expertise
       - Complex, long-cycle B2B deal experience
       - Revenue scaling and team building
       - DO NOT force healthcare angles
    3. Make NO claims about {company.name}'s business, products, or market unless you are CERTAIN they are true
    4. When in doubt, keep the pitch focused on universal sales leadership qualities
    
    **TASK**:
    1. **Strategist Analysis**: Generate 2 distinct angles SPECIFICALLY tailored to the "{wedge_type}" wedge.
       - Angle 1 should leverage the wedge directly
       - Angle 2 should be a complementary approach
       - RESPECT the company's actual vertical - do not force mismatched industry experience
    2. **Council Vote**: Select the best execution path based on:
       - Contact's role and decision-making authority
       - Company stage and urgency signals
       - Wedge strength and authenticity
       - FIT between candidate background and company's ACTUAL business
    3. **Draft Email**: Write the FINAL email (150-220 words) based on the winning angle.
    
    **STRICT RULES**:
    - No "synergies" or "partnership" language
    - No invented numbers ($90M+ allowed as it is in profile)
    - Wedge-specific: If "Growth Signal", reference the specific signal. If "Direct Role Match", reference the role.
    - NO FALSE CLAIMS about company's industry or business
    - Length: 150-220 words
    
    **OUTPUT JSON**:
    {{
        "insights": "Markdown string containing:\\n**Penetration Wedge:** {wedge_type}\\n**Angle 1 (Strategist):** ...\\n**Angle 2 (Dealmaker):** ...\\n**Council Decision:** ...",
        "outreach_angle": "Summary of the winning angle",
        "draft_email": "Final email text"
    }}
    """
    
    try:
        if use_local:
            # Use local DeepSeek-R1 (FREE, for batch processing)
            from ollama_client import call_ollama
            logger.info(f"Using local DeepSeek-R1 for {company.name} (FREE)")
            resp = call_ollama(prompt, model="deepseek-r1:32b", response_format="json")
            result = parse_json_from_llm(resp)
        else:
            # Use MiniMax API (FAST, for real-time alerts)
            logger.info(f"Using MiniMax API for {company.name} (fast mode)")
            resp = call_llm(prompt, response_format="json", forced_provider="minimax")
            result = parse_json_from_llm(resp)
        
        # Quality check - if result is poor, try one fallback
        if not result or not result.get("draft_email"):
            logger.warning(f"Primary model failed for {company.name}, using fallback")
            if use_local:
                # Fallback to MiniMax API
                resp = call_llm(prompt, response_format="json", forced_provider="minimax")
            else:
                # Fallback to DeepSeek API (still cheap at $0.14/M)
                resp = call_llm(prompt, response_format="json", forced_provider="deepseek")
            result = parse_json_from_llm(resp)
        
        # Step 3: Optional verification to catch hallucinations
        if verify and result and result.get("draft_email"):
            try:
                from verification_agent import verify_claims_with_perplexity
                verification = verify_claims_with_perplexity(
                    company.name,
                    result.get("draft_email"),
                    "healthcare"  # Candidate's primary vertical
                )
                
                if not verification['is_valid']:
                    logger.warning(f"⚠️  Draft for {company.name} FAILED verification!")
                    logger.warning(f"Issues: {verification['issues_found']}")
                    
                    # Flag the draft for review
                    result['draft_email'] = f"[⚠️  NEEDS REVIEW - Possible false claims]\n\n{result['draft_email']}"
                    result['verification_failed'] = True
                    result['verification_issues'] = verification['issues_found']
                else:
                    logger.info(f"✅ Draft for {company.name} passed verification (confidence: {verification['confidence']}%)")
                    result['verification_passed'] = True
                    
            except Exception as e:
                logger.warning(f"Verification skipped due to error: {e}")
        
        return result
    except Exception as e:
        logger.error(f"LLM Error for {company.name}: {e}")
        return None

def sync_leads():
    db = SessionLocal()
    try:
        # 1. Link jobs to companies
        jobs = db.query(Job).filter(Job.company_id == None).all()
        for j in jobs:
            if not j.company_name: continue
            co = db.query(Company).filter(Company.name.ilike(j.company_name)).first()
            if co: j.company_id = co.id
        db.commit()

        # 2. Sync high-fit jobs (Reactive) - Pulls shortlisted and scored jobs >= 60
        sync_candidates = db.query(Job).filter(Job.status.in_(['shortlisted', 'scored'])).all()
        for j in sync_candidates:
            # Skip 'scored' jobs if they are too low
            from models import JobScore
            js = db.query(JobScore).filter(JobScore.job_id == j.id).order_by(JobScore.created_at.desc()).first()
            if j.status == 'scored' and (not js or js.overall_score < 60):
                continue
                
            if not j.company_id: 
                # Auto-provision company if it doesn't exist
                logger.info(f"Auto-provisioning company: {j.company_name}")
                new_co = Company(
                    id=str(uuid.uuid4()),
                    name=j.company_name,
                    vertical=j.vertical or 'unknown',
                    hq_location=j.location,
                    fit_score=js.overall_score if js else 0
                )
                db.add(new_co)
                db.flush()
                j.company_id = new_co.id
                db.commit()
            
            # Check if we already have an outreach for this job
            existing = db.query(ProactiveOutreach).filter(
                ProactiveOutreach.company_id == j.company_id,
                # Check either by job_id or legacy signal match
                (ProactiveOutreach.job_id == j.id) | 
                (ProactiveOutreach.signal_summary.like(f"Job: %"))
            ).first()
            
            if not existing:
                logger.info(f"Drafting reactive lead for {j.company_name}")
                company = db.query(Company).get(j.company_id)
                contact = db.query(Contact).filter(Contact.company_id == j.company_id).order_by(Contact.confidence_score.desc()).first()
                
                # Generate Content (Handle missing contact)
                from scoring import score_job_posting
                job_rules_score = score_job_posting(company, j)
                
                if contact:
                    content = generate_outreach_content(company, contact, job=j, signal=f"Job Posting: {j.title}")
                else:
                    content = {
                        'outreach_angle': 'Contact Research Needed',
                        'insights': 'Found high-fit job but no decision-maker contact in DB yet.',
                        'draft_email': None
                    }

                if not content: continue

                outreach = ProactiveOutreach(
                    id=str(uuid.uuid4()), company_id=j.company_id, contact_id=contact.id if contact else None,
                    job_id=j.id,
                    outreach_type='job_intro', 
                    lead_type='job_posting',
                    signal_summary=f"Job: {j.title}",
                    fit_explanation=content.get('outreach_angle'),
                    insights=content.get('insights'),
                    draft_email=content.get('draft_email'),
                    priority_score=95, status='queued',
                    fit_score=job_rules_score,
                    next_action_at=datetime.utcnow(),
                    # Traceability metadata
                    job_url=j.url,
                    job_source=j.source,
                    job_location=j.location,
                    job_snippet=j.description[:500] if j.description else None,
                    role_title=j.title
                )
                db.add(outreach)
                
                # Log to Audit table
                from models import LeadCategorizationAudit
                audit = LeadCategorizationAudit(
                    company_name=j.company_name,
                    role_title=j.title,
                    job_url=j.url,
                    signal_source='lead_sync',
                    job_posting_detected=True,
                    final_lead_type='job_posting'
                )
                db.add(audit)
        
        # 3. Proactive: Pull high-fit companies
        top_universe = db.query(Company).filter(Company.fit_score >= 80).all()
        logger.info(f"Checking universe for {len(top_universe)} high-fit companies...")
        
        for co in top_universe:
            existing = db.query(ProactiveOutreach).filter(ProactiveOutreach.company_id == co.id).first()
            if not existing:
                contact = db.query(Contact).filter(Contact.company_id == co.id).order_by(Contact.confidence_score.desc()).first()
                if contact:
                    logger.info(f"Generating proactive draft for {co.name}...")
                    
                    from scoring import score_signal_lead
                    # Get signals for this company
                    from models import CompanySignal
                    signals = db.query(CompanySignal).filter(CompanySignal.company_id == co.id).all()
                    signal_rules_score = score_signal_lead(co, signals)
                    
                    content = generate_outreach_content(co, contact, signal="High Fit Score")
                    if content:
                        outreach = ProactiveOutreach(
                            id=str(uuid.uuid4()), company_id=co.id, contact_id=contact.id,
                            outreach_type='signal_intro', 
                            lead_type='signal_only',
                            signal_summary="Direct Universe Outreach",
                            fit_explanation=content.get('outreach_angle'),
                            insights=content.get('insights'),
                            draft_email=content.get('draft_email'),
                            priority_score=90, status='queued',
                            fit_score=signal_rules_score,
                            next_action_at=datetime.utcnow()
                        )
                        db.add(outreach)

                        # Log to Audit table
                        from models import LeadCategorizationAudit
                        audit = LeadCategorizationAudit(
                            company_name=co.name,
                            role_title=None,
                            job_url=None,
                            signal_source='lead_sync',
                            signal_only_detected=True,
                            final_lead_type='signal_only'
                        )
                        db.add(audit)
        
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    sync_leads()
