import logging
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from utils import call_llm, parse_json_from_llm
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# USER PROFILE - HARDCODED FOR CONSISTENCY
CANDIDATE_PROFILE = """
- Senior Commercial Executive (VP/SVP/CRO level) with 15+ years in Healthcare/Digital Health.
- Track record: Scaled revenue from $0 to $50M+, built high-performing sales teams.
- Expertise: Payer/Provider markets, Value-Based Care, Enterprise SaaS sales.
- Style: Consultative, strategic, player-coach.
"""

def generate_improved_draft(outreach, company, contact, job=None):
    """
    Generates a high-quality, hallucination-free draft using a constrained prompt.
    Returns: (insights, draft_email, outreach_angle) or None
    """
    
    # Construct Context
    job_context = ""
    if job:
        job_context = f"Applying for Role: {job.title}\nJob URL: {job.url}\n"
    
    prompt = f"""
    You are the "Council of Agents" for an executive job seeker. You are composed of three personas:
    1.  **The Strategist (DeepSeek)**: Analytical, focuses on business value, ROI, and competitor weakness.
    2.  **The Dealmaker (Minimax)**: Direct, bold, focuses on getting the meeting and the close.
    3.  **The Writer (Claude)**: Polished, human, concise, warm but professional.
    
    **YOUR GOAL**: Secure a conversation with {contact.name}, who is the {contact.title} at {company.name}.
    
    **YOUR PROFILE**:
    {CANDIDATE_PROFILE}
    
    **TARGET CONTEXT**:
    Company: {company.name} ({company.vertical})
    {job_context}
    Signal/Trigger: {outreach.signal_summary}
    
    **TASK**:
    1.  **Strategist Analysis**: Identify 2 distinct "Angles" (hooks) to approach this contact.
    2.  **Council Vote**: Select the best execution path.
    3.  **Draft Email**: Write the FINAL email based on the winning angle.
    
    **STRICT RULES**:
    - No "synergies" or "partnership".
    - No invented numbers ($90M+ allowed as it is in profile).
    - Length: 150-220 words.
    
    **OUTPUT JSON**:
    {{
        "insights": "Markdown string containing:\\n**Angle 1 (Strategist):** ...\\n**Angle 2 (Dealmaker):** ...\\n**Council Decision:** ...",
        "outreach_angle": "Summary of the winning angle",
        "draft_email": "Final email text"
    }}
    """
    
    try:
        response = call_llm(prompt, response_format="json")
        data = parse_json_from_llm(response)
        
        # Post-processing validation
        draft = data.get('draft_email', '')
        if '$' in draft or 'million' in draft.lower():
             draft = "[⚠️ REVIEW: Contains numbers] " + draft
        
        return data.get('insights'), draft, data.get('outreach_angle')
        
    except Exception as e:
        logger.error(f"LLM generation failed for {company.name}: {e}")
        return None, None, None

def regenerate_all_drafts():
    session = SessionLocal()
    try:
        # 1. Identify Drafts to Fix
        # We target specific "bad" patterns or null insights
        drafts_to_fix = session.query(ProactiveOutreach).filter(
            (ProactiveOutreach.insights == None) | 
            (ProactiveOutreach.draft_email.contains('$90M')) |
            (ProactiveOutreach.draft_email.contains('partnership'))
        ).all()
        
        logger.info(f"Found {len(drafts_to_fix)} drafts needing regeneration.")
        
        for i, outreach in enumerate(drafts_to_fix):
            logger.info(f"[{i+1}/{len(drafts_to_fix)}] Regenerating for {outreach.company.name}...")
            
            # Fetch related objects
            company = session.query(Company).get(outreach.company_id)
            contact = session.query(Contact).get(outreach.contact_id)
            job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
            
            if not company or not contact:
                logger.warning(f"Missing company/contact for outreach {outreach.id}, skipping.")
                continue

            # Generate
            insights, draft, angle = generate_improved_draft(outreach, company, contact, job)
            
            if draft:
                outreach.insights = insights
                outreach.draft_email = draft
                # update fit_explanation with angle if available
                if angle:
                    outreach.fit_explanation = angle
                
                # Commit immediately for safety
                session.commit()
                logger.info("Success.")
            
            # Rate limit politeness
            time.sleep(1) 

    except Exception as e:
        logger.error(f"Global error in regeneration: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    regenerate_all_drafts()
