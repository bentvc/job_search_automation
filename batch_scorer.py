"""
FIXED: Batch LLM Scoring with MiniMax
Now includes proper error handling and fallback to DeepSeek if MiniMax fails
"""
import logging
import config
from database import SessionLocal
from models import Job, JobScore
import requests
import json
import uuid
from utils import call_llm, parse_json_from_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def call_minimax_batch(jobs_batch):
    """Call MiniMax API with batch of jobs - FIXED version"""
    if not config.MINIMAX_API_KEY:
        logger.warning("MINIMAX_API_KEY not set, using fallback")
        return None
    
    # Prepare batch prompt
    jobs_summary = []
    for i, job in enumerate(jobs_batch):
        jobs_summary.append({
            "id": i,
            "title": job.title,
            "company": job.company_name,
            "description": (job.description or "")[:300]
        })
    
    prompt = f"""Score these {len(jobs_batch)} jobs for senior healthcare enterprise sales fit (0-100).

Candidate: {config.USER_PROFILE_SUMMARY}

Jobs:
{json.dumps(jobs_summary, indent=2)}

HIGH (80+): VP Sales, CRO, Strategic AE at payers/health tech
MID (60-79): Enterprise sales, healthcare adjacent  
LOW (<60): Sales Ops, entry-level, non-sales

Return ONLY valid JSON array:
[{{"id": 0, "score": 85, "reasoning": "VP Sales at payer"}}, ...]
"""
    
    try:
        # Try MiniMax
        response = requests.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={
                "Authorization": f"Bearer {config.MINIMAX_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "abab6.5s-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4000,
                "temperature": 0.1
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Extract JSON
            if "[" in content and "]" in content:
                json_start = content.index("[")
                json_end = content.rindex("]") + 1
                scores_json = content[json_start:json_end]
                parsed = json.loads(scores_json)
                logger.info(f"✅ MiniMax scored {len(parsed)} jobs")
                return parsed
        
        logger.warning(f"MiniMax failed: {response.status_code}, falling back to DeepSeek")
        return None
        
    except Exception as e:
        logger.warning(f"MiniMax error: {e}, falling back to DeepSeek")
        return None

def fallback_score_batch(jobs_batch):
    """Fallback to DeepSeek for batch scoring"""
    try:
        jobs_summary = []
        for i, job in enumerate(jobs_batch):
            jobs_summary.append({
                "id": i,
                "title": job.title,
                "company": job.company_name
            })
        
        prompt = f"""Score these jobs (0-100) for senior healthcare sales fit.
Jobs: {json.dumps(jobs_summary)}
Return JSON: [{{"id": 0, "score": 85, "reasoning": "..."}}]"""
        
        response = call_llm(prompt, response_format="json")  # Removed invalid provider arg
        parsed = parse_json_from_llm(response)
        
        # Handle if response is dict with 'scores' key or direct list
        if isinstance(parsed, dict) and 'scores' in parsed:
            return parsed['scores']
        elif isinstance(parsed, list):
            return parsed
        
        logger.warning("DeepSeek returned unexpected format")
        return None
        
    except Exception as e:
        logger.error(f"Fallback scoring failed: {e}")
        return None

def batch_score_jobs(batch_size=50):  # Reduced from 100 for reliability
    """Score all unscored jobs in batches"""
    db = SessionLocal()
    try:
        # Get unscored jobs
        unscored = db.query(Job).outerjoin(JobScore).filter(
            Job.status == 'new',
            JobScore.id == None
        ).limit(500).all()
        
        if not unscored:
            logger.info("No unscored jobs found")
            return 0
        
        logger.info(f"📊 Batch scoring {len(unscored)} jobs...")
        scored_count = 0
        
        # Process in batches
        for i in range(0, len(unscored), batch_size):
            batch = unscored[i:i+batch_size]
            logger.info(f"Batch {i//batch_size + 1}/{(len(unscored)-1)//batch_size + 1} ({len(batch)} jobs)")
            
            # Try MiniMax first
            scores_response = call_minimax_batch(batch)
            
            # Fallback to DeepSeek if MiniMax fails
            if not scores_response:
                logger.info("Using DeepSeek fallback...")
                scores_response = fallback_score_batch(batch)
            
            if not scores_response:
                logger.warning(f"Batch {i//batch_size + 1} failed completely, skipping")
                continue
            
            # Apply scores
            for score_data in scores_response:
                idx = score_data.get("id")
                if idx is None or idx >= len(batch):
                    continue
                
                job = batch[idx]
                score_value = score_data.get("score", 0)
                reasoning = score_data.get("reasoning", "")
                
                # Create JobScore
                job_score = JobScore(
                    id=str(uuid.uuid4()),
                    job_id=job.id,
                    overall_score=score_value,
                    notes=reasoning
                )
                db.add(job_score)
                
                # Update job status
                if score_value >= 80:
                    job.status = 'shortlisted'
                elif score_value >= 60:
                    job.status = 'scored'
                else:
                    job.status = 'rejected'
                
                scored_count += 1
            
            db.commit()
            logger.info(f"✅ Batch complete: {scored_count} jobs scored so far")
        
        logger.info(f"✅ Batch scoring complete: {scored_count} total jobs scored")
        return scored_count
        
    finally:
        db.close()

if __name__ == "__main__":
    batch_score_jobs()
