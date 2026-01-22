# 🤖 AUTOMATED HIGH-VOLUME PIPELINE - ACTIVE

## 🎯 CURRENT STATUS: **RUNNING**

**Start Time**: 2026-01-22 15:49 MST  
**Mode**: Fully Automated Sequential Execution  
**ETA**: ~30-45 minutes for complete pipeline

---

## 📋 EXECUTION PLAN (8 PHASES)

### ✅ Phase 1: Multi-Site Job Scraper
- **Status**: 🔄 RUNNING (in progress)
- **Sources**: LinkedIn, Indeed, Glassdoor (Z ipRecruiter blocked)
- **Queries**: 18 healthcare/payer queries
- **Expected**: 1,500-2,500 new jobs
- **Duration**: ~15-20 minutes

### ⏳ Phase 2: Batch LLM Scoring
- **Status**: ⏳ Queued (waits for Phase 1)
- **Model**: MiniMax 2.1 (fallback: DeepSeek)
- **Expected**: Score all unscored jobs
- **Cost**: <$0.10
- **Duration**: ~5 minutes

### ⏳ Phase 3: Y Combinator Healthcare
- **Status**: ⏳ Queued
- **Expected**: 100-300 healthcare startups
- **Duration**: ~2 minutes

### ⏳ Phase 4: Direct ATS Scraping
- **Status**: ⏳ Queued
- **Targets**: 21 companies (Greenhouse + Lever)
- **Expected**: 50-200 jobs
- **Duration**: ~5 minutes

### ⏳ Phase 5: Rock Health Funding
- **Status**: ⏳ Queued
- **Expected**: 200-500 funded companies
- **Duration**: ~3 minutes

### ⏳ Phase 6: Healthcare Job Boards
- **Status**: ⏳ Queued
- **Sources**: MedReps, HealthcareJobSite, Health eCareers
- **Expected**: 100-300 jobs
- **Duration**: ~5 minutes

### ⏳ Phase 7: RSS Funding News
- **Status**: ⏳ Queued
- **Sources**: TechCrunch, Fierce Healthcare, etc.
- **Expected**: 20-50 funding signals
- **Duration**: ~2 minutes

### ⏳ Phase 8: Sync & Generate Outreach
- **Status**: ⏳ Queued
- **Action**: Link companies, generate drafts
- **Expected**: 50-100 new queued outreach items
- **Duration**: ~5 minutes

---

## 📊 CURRENT METRICS (Baseline)

```
Total Jobs:        361
Shortlisted:       9
Active Companies:  25
Queued Outreach:   24
```

## 🎯 EXPECTED END STATE

```
Total Jobs:        3,000-5,000+
Shortlisted:       100-200+
Active Companies:  500-1,000+
Queued Outreach:   80-150+
Funding Signals:   50-100+
```

---

## 🖥️ MONITORING OPTIONS

### Real-Time Status:
```bash
python monitor_automation.py
```
*Shows which phase is running + live stats (updates every 15 sec)*

### Detailed Logs:
```bash
tail -f automated_pipeline.log
```
*Full output from all scrapers*

### Database Stats:
```bash
python monitor_pipeline.py
```
*Detailed breakdowns by source, status, etc.*

### Quick Check:
```bash
sqlite3 data/job_search.db "SELECT COUNT(*) FROM jobs;"
```

---

## ⚡ WHAT HAPPENS AUTOMATICALLY

1. **Multi-Site Scraper** completes → Moves to Batch Scoring
2. **Batch Scorer** finishes → Moves to YC Scraper
3. **Each phase** triggers the next automatically
4. **Final phase** restarts Streamlit dashboard with fresh data
5. **You get notified** when complete (check logs)

---

## 🛑 IF YOU NEED TO STOP

```bash
# Stop all scrapers
pkill -f "scraper_"
pkill -f "batch_scorer"
pkill -f "sync_leads"

# Stop automation orchestrator
pkill -f "run_automated_pipeline"
```

---

## ✅ WHEN COMPLETE

The automation script will:
1. Generate final statistics
2. Restart the Streamlit dashboard
3. Output completion message to `automated_pipeline.log`

**Dashboard will be live at**: http://localhost:8501

---

## 📈 SUCCESS CRITERIA

### Minimum Success (Phase 1-2):
- ✅ 1,000+ jobs discovered
- ✅ 50+ shortlisted
- ✅ Batch scoring <$0.15

### Full Success (All Phases):
- 🎯 3,000+ jobs discovered
- 🎯 150+ shortlisted
- 🎯 500+ companies in universe
- 🎯 100+ queued outreach opportunities
- 🎯 Total cost <$0.30

---

## 🔧 POST-COMPLETION TASKS

Once pipeline finishes, you can:

1. **Review Dashboard** at `http://localhost:8501`
2. **Process Outreach Queue** - Review and send emails
3. **Schedule Daily Runs**:
   ```bash
   # Add to crontab
   0 */6 * * * cd /path/to/project && ./run_automated_pipeline.sh
   ```
4. **Refine Queries** - Adjust `config.py` based on results
5. **Expand Sources** - Add more job boards/company directories

---

**Status**: 🟢 ACTIVE  
**Last Updated**: 2026-01-22 15:50 MST  
**Monitor**: `python monitor_automation.py`
