# Optimized Council Configuration

## Two-Mode Operation

### Mode 1: Batch Processing (Overnight/Scheduled)
**Use 100% local DeepSeek-R1 - ZERO COST**

```python
# In sync_leads.py or fix_and_regenerate.py
content = generate_outreach_content(
    company, 
    contact, 
    job=job, 
    signal=signal,
    use_local=True  # FREE - use local DeepSeek-R1
)
```

**Characteristics:**
- Cost: $0.00
- Speed: ~30-60 seconds per outreach
- Quality: Excellent reasoning and writing
- Best for: Daily queue processing (1-2x per day)

### Mode 2: Real-Time Alerts (New Job Posted)
**Use MiniMax API - ULTRA-CHEAP & FAST**

```python
# In agent1_job_scraper.py when new high-priority job detected
content = generate_outreach_content(
    company, 
    contact, 
    job=job, 
    signal=signal,
    use_local=False  # FAST - use MiniMax API (~$0.004 per job)
)
```

**Characteristics:**
- Cost: ~$0.004 per outreach
- Speed: <5 seconds
- Quality: Good enough for immediate response
- Best for: Time-sensitive new job alerts

## Estimated Costs

### Scenario 1: Daily Queue Processing (20 outreach/day)
- **Local DeepSeek-R1**: $0.00/day
- **Annual cost**: $0.00

### Scenario 2: Real-Time Alerts (5 urgent jobs/day)
- **MiniMax API**: $0.02/day
- **Annual cost**: ~$7.30

### Scenario 3: Mixed (15 batch + 5 urgent/day)
- **Batch (local)**: $0.00
- **Alerts (MiniMax)**: $0.02
- **Daily total**: $0.02/day
- **Annual cost**: ~$7.30

**Compare to previous run**: That one expensive session cost $20-30. At the new rate, you could run for 3-4 YEARS for the same cost!

## Implementation

### For Batch Processing (Current Use Case)
```bash
# Run overnight with local models
python3 sync_leads.py --use-local

# Or in cron job
0 2 * * * cd /path/to/project && python3 sync_leads.py --use-local
```

### For Real-Time Alert System (Future)
```python
# In agent1_job_scraper.py
if job.score >= 90 and job.is_fresh:  # High priority + just posted
    # Use fast API mode for immediate draft
    content = generate_outreach_content(
        company, contact, job, 
        use_local=False  # Speed priority
    )
    send_alert_email(content)
```

## Quality vs Speed Trade-off

| Model | Cost | Speed | Quality | Best For |
|-------|------|-------|---------|----------|
| DeepSeek-R1 Local | $0 | 30-60s | ⭐⭐⭐⭐⭐ | Batch processing |
| MiniMax API | $0.004 | 3-5s | ⭐⭐⭐⭐ | Real-time alerts |
| DeepSeek API | $0.001 | 5-8s | ⭐⭐⭐⭐ | Fallback |
| Gemini Flash | $0.01 | 2-3s | ⭐⭐⭐⭐ | Polish only |

## Recommendation for Your Workflow

**Current (1-2x daily queue processing)**:
- ✅ Use DeepSeek-R1 local (free)
- ✅ Process overnight or during lunch
- ✅ No need for speed optimization

**Future (with job alert system)**:
- ✅ Batch processing: DeepSeek-R1 local
- ✅ New job alerts: MiniMax API (speed matters)
- ✅ Total cost: <$10/month even with 10 urgent alerts/day

## Testing the Local Setup

```bash
# Test local DeepSeek-R1
python3 ollama_client.py

# Test one outreach with local model
python3 -c "
from sync_leads import generate_outreach_content
from database import SessionLocal
from models import Company, Contact

db = SessionLocal()
company = db.query(Company).first()
contact = db.query(Contact).filter(Contact.company_id == company.id).first()

content = generate_outreach_content(company, contact, use_local=True)
print('Success!' if content else 'Failed')
db.close()
"
```

## Alert System Design (Future Enhancement)

```python
# In agent1_job_scraper.py

def check_for_urgent_jobs():
    """Check for high-priority jobs that need immediate outreach."""
    new_jobs = get_jobs_posted_last_hour()
    
    for job in new_jobs:
        if job.score >= 90:  # Only urgent high-fit jobs
            logger.info(f"🚨 URGENT: {job.title} at {job.company_name}")
            
            # Fast draft with API
            content = generate_outreach_content(
                job.company, 
                job.contact,
                job=job,
                use_local=False  # Speed priority
            )
            
            # Send notification
            send_slack_alert(f"New urgent job: {job.title}")
            send_email_alert(content)
```

This gives you the best of both worlds: FREE for daily work, FAST for urgent opportunities.
