# SYSTEM ARCHITECTURE REFRESH: HIGH-VOLUME JOB SEARCH & SIGNAL ENGINE
## Problem Statement
Current system is fundamentally limited by:
1. **Low Job Volume**: Single-threaded scraper hitting 1-2 sources → ~342 jobs total
2. **Weak Signal Intelligence**: Relying on manual lists + broken BuiltIn scraping
3. **LLM Cost**: Using expensive models (GPT-4) for all tasks
4. **No Parallelization**: Sequential processing of everything

## Target Performance
- **Jobs**: 10,000+ relevant postings/week (vs current ~50/week)
- **Companies**: 1,000+ high-fit targets with live intelligence
- **Signals**: Real-time monitoring of funding, hiring spikes, news
- **Cost**: <$20/week in LLM usage

---

## NEW ARCHITECTURE

### Phase 1: Explosive Job Discovery (Immediate)
**Multi-Source Parallel Scraper** - Hit 15+ sources simultaneously:

#### Tier 1: Aggregator APIs (Fast, High Volume)
1. **JobSpy Enhancement** (already integrated)
   - Enable ALL sites: LinkedIn, Indeed, ZipRecruiter, Glassdoor, Google
   - Parallel queries: 10 searches × 100 results = 1,000 jobs/run
   
2. **Adzuna API** (Free tier: 250 calls/month)
   - Healthcare-specific queries
   - Regex: `/(payer|health plan|managed care|revenue|sales)/i`

3. **GitHub Jobs API Alternative**: **Remotive.io API**
   - Remote healthcare tech roles

#### Tier 2: Direct ATS Scraping (Company Career Pages)
Bypass job boards entirely—scrape directly from:
- **Greenhouse** boards: `/boards.greenhouse.io/[company]`
- **Lever** boards: `/jobs.lever.co/[company]`
- **Workday** public boards (harder but high-value)

**Implementation**: 
- Maintain a list of 500 target companies
- Async scraper hits each career page every 48 hours
- Example targets from your space:
  - Humana, Cigna, Optum, Molina (payer)
  - Healthgrades, Doximity (health tech)
  - All YC Health companies

#### Tier 3: Niche Boards (Healthcare Focus)
- **HealthcareJobSite.com**
- **MedReps** (medical sales specific)
- **BuiltIn** (but with strict filtering we just added)

### Phase 2: Industrial-Scale Signal Mining

#### Source Diversification (No Crunchbase)
**Alternative Data Sources**:

1. **Wellfound (AngelList)** - Startup directory
   - Free access to company profiles, funding info
   - Scrape: `/wellfound.com/company/[slug]`

2. **PitchBook Free Tier**
   - Limited but gets you recent fundings

3. **YC Company Directory** 
   - `/ycombinator.com/companies`
   - Filter by healthcare/fintech/B2B
   - ~4,000 companies, all with funding data

4. **LinkedIn Company Pages**
   - Employee growth rate (signal of hiring)
   - Recent posts mentioning "we're hiring"
   
5. **RSS/Newsletter Scraping**:
   - TechCrunch funding announcements
   - Rock Health newsletter (weekly healthcare funding)
   - Fierce Healthcare

6. **SEC Edgar Filings** (for public payers)
   - 8-K filings = major events (exec hires, M&A)

#### Signal Types to Track
- 📈 **Growth**: Employee count +20% in 90 days (LinkedIn)
- 💰 **Funding**: Any round (Wellfound, TC, newsletters)
- 📢 **Hiring Spike**: 5+ new roles posted in 7 days
- 🏆 **Awards/Press**: Industry recognition (RSS scrape)
- 🔄 **Leadership Changes**: New CRO/VP Sales (LinkedIn, press)

### Phase 3: Cost Optimization (LLM Strategy)

**Tiered Model Selection**:
```
┌─────────────────────────────────┬──────────────────┬─────────────┐
│ Task                            │ Model            │ Cost/1M tok │
├─────────────────────────────────┼──────────────────┼─────────────┤
│ Job Relevance Filter (Yes/No)   │ MiniMax 2.1      │ $0.005      │
│ Company Fit Scoring (0-100)     │ DeepSeek R1      │ $0.14       │
│ Email Draft Generation          │ K2 / DeepSeek V3 │ $0.28       │
│ Complex Strategy (rare)         │ Claude 3.5       │ $3.00       │
└─────────────────────────────────┴──────────────────┴─────────────┘
```

**Batch Processing**:
- Collect 100 jobs → Single LLM call with array response
- Vs. current: 1 call per job

---

## IMPLEMENTATION ROADMAP

### Week 1: Foundation (Next 48 Hours)
✅ Add MiniMax to utils.py
⬜ Refactor Agent 1 to use JobSpy for ALL sites
⬜ Create `batch_scorer.py` - 100 jobs/call with MiniMax
⬜ Build ATS scraper for Greenhouse/Lever (top 50 companies)

### Week 2: Signal Explosion
⬜ Wellfound scraper (YC + healthcare startups)
⬜ RSS aggregator for funding news
⬜ LinkedIn company monitor (growth tracking)

### Week 3: Automation
⬜ Orchestration: Celery/RQ for background queue processing
⬜ Daily cron: scrape 15 sources → dedupe → batch score
⬜ Real-time dashboard updates

---

## QUICK WINS (Next 2 Hours)

1. **Enable All JobSpy Sites**
```python
# Current: site_name=["linkedin"]
# New: site_name=["linkedin", "indeed", "ziprecruiter", "glassdoor"]
```

2. **Batch LLM Scoring**
```python
def batch_score_jobs(jobs_list):
    prompt = f"Score these {len(jobs_list)} jobs for fit [1-100]..."
    # Single API call for 100 jobs vs 100 calls
```

3. **Greenhouse Scraper** (15 lines of code)
```python
for company in ["humana", "cigna", "optum"]:
    resp = requests.get(f"https://boards.greenhouse.io/{company}/jobs")
    # Parse job links
```

4. **Wellfound Healthcare Scraper**
```python
# Wellfound has a clean API-like structure
# GET https://wellfound.com/role/l/software-engineer/skill/python
```

---

## MEASURING SUCCESS

**Current Baseline**:
- Jobs: 342 total, ~20 shortlisted
- Companies: 76 monitored, ~14 real
- Leads: 24 in queue

**Target (Week 1)**:
- Jobs: 2,000+ scraped, 100+ shortlisted
- Companies: 500 real companies monitored
- Leads: 50+ high-signal outreach opportunities

**Target (Week 4)**:
- Jobs: 10,000+ in DB, 500+ shortlisted
- Companies: 2,000 in universe with live signals
- Leads: Daily queue of 20+ fresh opportunities
- Cost: <$15/week LLM

---

## NEXT STEPS

I'm ready to implement:
1. Multi-site JobSpy upgrade (5 minutes)
2. Batch scoring with MiniMax (20 minutes)
3. Greenhouse/Lever scraper (30 minutes)
4. Wellfound startup directory scraper (45 minutes)

Which should I start with?
