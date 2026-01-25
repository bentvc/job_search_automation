import logging
import pandas as pd
from jobspy import scrape_jobs
from database import SessionLocal
from models import Job, JobScore
import config
from utils import call_llm, parse_json_from_llm
from rate_limiter import rate_limit
import hashlib
from datetime import datetime, timedelta
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure debug directory exists
DEBUG_DIR = "/home/bent-christiansen/.gemini/antigravity/scratch/job_search_automation/debug"
os.makedirs(DEBUG_DIR, exist_ok=True)

def get_selected_provider():
    """Reads the LLM provider selected in the UI."""
    try:
        with open("provider_settings.json", "r") as f:
            return json.load(f).get("provider", "openai")
    except:
        return "openai"

def run_jobspy_search(query: str, hours_old: int = 72) -> pd.DataFrame:
    """
    JobSpy search - intended to be called in a thread.
    """
    all_sites = ["indeed", "linkedin", "zip_recruiter", "glassdoor", "google"]
    results_per_site = 100
    
    try:
        logger.info(f"🚀 Scraping: '{query}'")
        jobs = scrape_jobs(
            site_name=all_sites,
            search_term=query,
            location="United States",
            results_wanted=results_per_site * len(all_sites),
            hours_old=hours_old,
            country_indeed='USA',
            linkedin_fetch_description=True
        )
        
        if not jobs.empty:
            counts = jobs['site'].value_counts().to_dict()
            logger.info(f"📊 Stats for '{query}': {counts}")
            return jobs
    except Exception as e:
        logger.error(f"❌ Scrape failed for '{query}': {e}")
    return pd.DataFrame()

def save_and_queue_job(job_row: pd.Series):
    """Saves job to DB with status='new'."""
    db = SessionLocal()
    try:
        title = str(job_row.get('title', '')).lower().strip()
        company = str(job_row.get('company', '')).lower().strip()
        clean_title = title.split('(@')[0].split(' - ')[0].strip()
        key_str = f"{company}|{clean_title}"
        dedupe_key = hashlib.md5(key_str.encode()).hexdigest()
        
        existing = db.query(Job).filter(Job.dedupe_key == dedupe_key).first()
        if existing: return None
            
        raw_dict = job_row.to_dict()
        for k, v in raw_dict.items():
            if isinstance(v, (datetime, timedelta)): raw_dict[k] = str(v)
            elif hasattr(v, 'isoformat'): raw_dict[k] = v.isoformat()

        # Try to link to a company in our universe
        comp = db.query(Company).filter(Company.name.ilike(job_row.get('company', ''))).first()
        company_id = comp.id if comp else None

        new_job = Job(
            title=job_row.get('title'),
            company_name=job_row.get('company'),
            company_id=company_id,
            location=job_row.get('location'),
            url=job_row.get('job_url'),
            description=job_row.get('description'),
            dedupe_key=dedupe_key,
            source=job_row.get('site'),
            status='new', # Ready to be scored
            raw_data=raw_dict
        )
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        return new_job.id
    except Exception as e:
        logger.error(f"Save error: {e}")
        return None
    finally:
        db.close()

def score_job_concurrent(job_id, provider):
    """Threaded scoring function."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.status != 'new': return
        
        # Fast nuke for non-roles
        title_l = job.title.lower()
        if any(x in title_l for x in ["operations", "enablement", "support", "admin", "specialist"]) and "vp" not in title_l and "director" not in title_l:
            job.status = 'rejected'
            db.commit()
            return

        prompt = f"""
        Score this role for a senior Healthcare/Fintech Enterprise Sales professional.
        Profile: {config.USER_PROFILE_SUMMARY}
        Job: {job.title} at {job.company_name}
        Desc: {job.description[:3000] if job.description else 'N/A'}

        SCORING RULES:
        1. OVERALL_SCORE: 0-100.
           - DIRECT VERTICAL BOOST: High preference for Payer, Health Plan, Medicaid, Medicare Advantage. 
           - SECONDARY BOOST: High interest in Healthtech, Fintech (B2B payments/infrastructure).
           - GENERIC CAP: Generic B2B SaaS (logistics, CRM, etc.) should stay below 70 unless truly exceptional enterprise fit.
           - HARD KILL: "Sales Operations", "Sales Enablement", "RevOps" must be scored < 35.
        2. VERTICAL: Classify as "payer", "healthcare", "fintech", "general_saas", or "other".
        3. Explain reasoning in 'explanation'.

        Return JSON: {{"overall_score": int, "vertical": "string", "explanation": "string"}}
        """
        
        from scoring import score_job_posting
        rules_score = score_job_posting(job.company, job)
        
        response = call_llm(prompt, response_format="json", forced_provider=provider)
        result = parse_json_from_llm(response)
        
        if result:
            llm_score = result.get('overall_score', 0)
            vert = result.get('vertical', 'other').lower()
            
            # Combine scores: 60% LLM, 40% Rules
            final_score = int(llm_score * 0.6 + rules_score * 0.4)
            
            # Post-processing hard overrides
            # 1. Sales Ops / Enablement Nuke - 100% enforcement
            ops_terms = ["sales operations", "sales ops", "enablement", "revops", "revenue operations", "rev ops", "coordinator", "assistant"]
            if any(term in title_l for term in ops_terms) and "vp" not in title_l and "director" not in title_l:
                final_score = min(final_score, 30)
                job.status = 'rejected'
            
            # 2. Rejection for low scores
            if final_score < 40:
                job.status = 'rejected'
            elif final_score >= 80:
                job.status = 'shortlisted'
            else:
                job.status = 'scored'

            db.add(JobScore(job_id=job.id, overall_score=final_score, notes=result.get('explanation', '')))
            
            # Log to Audit table
            from models import LeadCategorizationAudit
            audit = LeadCategorizationAudit(
                company_name=job.company_name,
                role_title=job.title,
                job_url=job.url,
                signal_source='job_scraper',
                job_posting_detected=True,
                final_lead_type='job_posting'
            )
            db.add(audit)
            
            job.vertical = vert
            # Update job fit_score for queue prioritization
            job.fit_score_boost = final_score # Just for internal tracking if needed, but we use JobScore
            db.commit()
            logger.info(f"✅ Scored ({provider}): {job.title} -> {final_score} (LLM: {llm_score}, Rules: {rules_score}) [{vert}]")
    except Exception as e:
        logger.error(f"Scoring error for job {job_id}: {e}")
    finally:
        db.close()

def run_agent1_parallel(test_run=False):
    """
    Parallelized Mining and Brain execution.
    """
    provider = get_selected_provider()
    queries = config.JOBSPY_QUERIES[:2] if test_run else config.JOBSPY_QUERIES
    
    # Phase 1: Parallel Mining
    logger.info(f"🚀 Phase 1: Mining {len(queries)} queries...")
    all_job_ids = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_jobspy_search, q): q for q in queries}
        for future in as_completed(futures):
            df = future.result()
            if not df.empty:
                for _, row in df.iterrows():
                    jid = save_and_queue_job(row)
                    if jid: all_job_ids.append(jid)

    # Phase 2: Parallel Brain (Scoring)
    logger.info(f"🧠 Phase 2: Scoring {len(all_job_ids)} new roles using {provider}...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(lambda jid: score_job_concurrent(jid, provider), all_job_ids)

    logger.info("🏁 Parallel run complete.")

if __name__ == "__main__":
    import sys
    is_test = "--test" in sys.argv
    run_agent1_parallel(test_run=is_test)
