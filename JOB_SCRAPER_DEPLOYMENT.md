# Job Scraper – Packaging & Deployment Guide

This document suggests how to **package and deploy** the job-scraper parts of this project for a friend (locally or in the cloud). **No changes to existing behavior are recommended here**—only packaging, configuration, and deployment options.

---

## 1. What “Job Scraper” Includes

You have two main ways to run job discovery:

| Mode | Entrypoint | What it does |
|------|------------|--------------|
| **Agent 1 only** | `python agent1_job_scraper.py` | JobSpy (Indeed, LinkedIn, ZipRecruiter, Glassdoor, Google) → LLM + rules scoring → DB |
| **Multi-scraper pipeline** | `./run_quick_wins.sh` or `./run_complete_pipeline.sh` | Multiple scrapers (multisite, ATS, YC/Wellfound, Rock Health, niche boards, RSS) + batch scoring |

**Suggested scope for your friend:**

- **Minimal:** Agent 1 + SQLite + one LLM provider. Quick to set up, single script.
- **Fuller experience:** Multi-scraper pipeline + Streamlit UI. More sources, dashboard, same DB.

---

## 2. Pre-Flight Checklist (Before Sharing)

These **do not modify behavior** but are worth fixing or documenting before someone else runs it:

1. **`agent1_job_scraper.py`**
   - `Company` is used in `save_and_queue_job` (line ~77) but **not imported** from `models`. Add `Company` to the `models` import or the code will raise `NameError` when linking jobs to companies.
   - `job.fit_score_boost` is assigned (line ~179). The `Job` model defines `vertical_score_boost`, not `fit_score_boost`. Either add the column (migration) or use `vertical_score_boost` so scoring doesn’t hit `AttributeError`.
   - **`DEBUG_DIR`** is hardcoded to your path (`/home/bent-christiansen/...`). On your friend’s machine this will create directories under that path if it exists, or fail. Consider `DEBUG_DIR = os.getenv("JOB_SCRAPER_DEBUG_DIR", os.path.join(os.getcwd(), "debug"))` or similar.

2. **`scheduler.py`**
   - Imports `run_agent1_scraper`, but `agent1_job_scraper` exposes `run_agent1_parallel`. The scheduler will fail on import. Either point the scheduler at `run_agent1_parallel` or add a `run_agent1_scraper` wrapper that calls it.

3. **`.env.template`**
   - README says `cp .env.template .env`, but there is no `.env.template` in the repo. Add one with placeholder keys (see below) so your friend knows what to set.

4. **`provider_settings.json`**
   - Agent 1 uses this for LLM provider selection (e.g. `openrouter`). Include it in the package; your friend can change `"provider"` to match their keys.

---

## 3. What to Package

### Minimal (Agent 1 only)

- **Scripts:** `agent1_job_scraper.py`
- **Core:** `config.py`, `database.py`, `models.py`, `scoring.py`, `utils.py`, `rate_limiter.py`
- **Config:** `config/` (e.g. `scoring_weights.yaml`; `golden_leads.yaml` if scoring uses it)
- **Data:** `data/` directory (empty or with `.gitkeep`); DB path `data/job_search.db` by default
- **Env:** `.env.template` (see Section 6)
- **Deps:** `requirements.txt`

### Multi-scraper pipeline

Add:

- **Scrapers:** `scraper_multisite.py`, `scraper_ats.py`, `scraper_startups.py`, `scraper_rock_health.py`, `scraper_niche_boards.py`, `scraper_rss_funding.py`, and any `scraper_yc_fixed` / `scraper_wellfound_fixed` you use
- **Scoring:** `batch_scorer.py`
- **Scripts:** `run_quick_wins.sh`, `run_complete_pipeline.sh` (and `run_automated_pipeline.sh` if desired)
- **Optional:** `sync_leads.py` if you want lead sync in the pipeline

### With Streamlit UI

- **UI:** `ui_streamlit.py`
- **Extra deps:** already in `requirements.txt` (e.g. `streamlit`)
- **Optional:** `provider_settings.json` so the UI can switch LLM provider

### Optional (if they use those features)

- **Scheduler:** `scheduler.py`, `agent2_signal_monitor.py`, `agent3_universe_builder.py` (only if you fix scheduler import and they use those agents)
- **Apollo / outreach:** `apollo_client.py`, `agent4_contact_finder.py`, `agent5_outreach_sequencer.py`, `mailgun_client.py`, etc. Only needed for contact finding and email outreach, not for scraping/scoring alone.

---

## 4. Dependencies

- **Python:** 3.11+ (Dockerfile uses 3.11).
- **System:** Playwright Chromium for some scrapers (`playwright install --with-deps chromium`). Required if using JobSpy with LinkedIn or similar; otherwise job-scraper may still run with fewer sites.
- **Python packages:** `requirements.txt`. Key ones for job scraper: `python-jobspy`, `sqlalchemy`, `pandas`, `python-dotenv`, `openai`, `anthropic`, etc. For batch scoring, `requests` (MiniMax) and whatever `utils.call_llm` uses (OpenAI, Anthropic, OpenRouter, etc.).

---

## 5. Environment Variables

**Minimum for job scraper + scoring:**

- **Database:** `DATABASE_URL` (optional). Default `sqlite:///./data/job_search.db`. Use Postgres for multi-worker/cloud if you like.
- **At least one LLM provider:**
  - `OPENAI_API_KEY`, or  
  - `ANTHROPIC_API_KEY`, or  
  - `OPENROUTER_API_KEY`, or  
  - `DEEPSEEK_API_KEY`, or  
  - `MINIMAX_API_KEY` (used by `batch_scorer` and possibly `utils.call_llm`)

Set `provider` in `provider_settings.json` to match the key they use (e.g. `openrouter`, `openai`).

**Not needed for scraping/scoring only:** Apollo, Mailgun, News/X API keys, Perplexity, etc.

---

## 6. `.env.template`

A `.env.template` exists in the project root (and is tracked; `.env` remains gitignored). Your friend copies it to `.env` and fills in keys. Example structure:

```bash
# Database (optional; default: sqlite:///./data/job_search.db)
# DATABASE_URL=sqlite:///./data/job_search.db

# At least one LLM provider for scoring
# OPENAI_API_KEY=your_openai_key
# ANTHROPIC_API_KEY=your_anthropic_key
OPENROUTER_API_KEY=your_openrouter_key
# DEEPSEEK_API_KEY=your_deepseek_key
# MINIMAX_API_KEY=your_minimax_key

# Optional: debug output directory for agent1 (if you make it configurable)
# JOB_SCRAPER_DEBUG_DIR=./debug
```

Your friend copies to `.env`, fills in real keys, and leaves unused providers commented out.

---

## 7. Local Deployment

### Option A: venv + SQLite (simplest)

```bash
cd /path/to/job_search_automation
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install --with-deps chromium

cp .env.template .env
# Edit .env: add at least one LLM API key

mkdir -p data
python3 -c "from database import init_db; init_db()"
```

**Run job scraper only:**

```bash
python agent1_job_scraper.py
# Or test run (fewer queries): python agent1_job_scraper.py --test
```

**Run multi-scraper pipeline:**

```bash
chmod +x run_quick_wins.sh
./run_quick_wins.sh
# Or run_complete_pipeline.sh for all 7 scrapers
```

**Run Streamlit UI:**

```bash
streamlit run ui_streamlit.py
# Default: http://localhost:8501
```

### Option B: Docker Compose (UI + scraper)

You have `docker-compose.yml.bak` with `ui`, `scheduler`, and `scraper` services. To use it:

- Restore it as `docker-compose.yml` (or adapt the following to your actual compose file).
- Ensure `env_file: .env` and that `.env` exists with required keys.
- `scraper` runs `python agent1_job_scraper.py` once and exits; Compose will restart it if you use `restart: on-failure` or similar. For **repeated** runs, use a cron job or scheduler instead of relying only on Compose restart.

Example:

```bash
cp docker-compose.yml.bak docker-compose.yml
# Edit docker-compose.yml if needed (e.g. add restart policy for scraper)
cp .env.template .env && $EDITOR .env
docker compose up -d
```

Scraper runs as configured; UI on port 8501.

---

## 8. Cloud Deployment

### 8.1 Docker on a VPS (Railway, Render, Fly.io, EC2, etc.)

- **Build:** Use your existing `Dockerfile` (Streamlit + app code). Optionally add a second Dockerfile or target that only runs the scraper (e.g. `CMD ["python", "agent1_job_scraper.py"]`).
- **Database:** Use `DATABASE_URL` pointing to a managed Postgres (Railway, Render, Supabase, RDS) so the DB persists across restarts. For SQLite, mount a volume and use `sqlite:///./data/job_search.db`; be aware of concurrent-write and backup limits.
- **Secrets:** Provide env vars via the platform’s secrets/config (no `.env` in repo).
- **Scraper as batch job:** Run the scraper on a schedule (cron inside the container, or platform cron/Lambda-style jobs) rather than as a long-running service. Same for `run_quick_wins.sh` / `run_complete_pipeline.sh` if you use them.

### 8.2 Run scraper on a schedule

- **Inside Docker:** Add a cron job (or a small scheduler process) that runs `python agent1_job_scraper.py` or `./run_quick_wins.sh` at desired intervals.
- **Outside Docker:** Use system cron on a VPS:

  ```cron
  0 */6 * * * cd /path/to/job_search_automation && .venv/bin/python agent1_job_scraper.py >> /var/log/job_scraper.log 2>&1
  ```

### 8.3 Streamlit in the cloud

- Streamlit Cloud, Hugging Face Spaces, or a container running `streamlit run ui_streamlit.py` (as in your Dockerfile) all work. Ensure:
  - Env vars (especially LLM keys) are configured.
  - `data/` (or wherever the DB lives) is persistent if using SQLite.

### 8.4 Playwright / Chromium in Docker

Your Dockerfile already runs `playwright install --with-deps chromium`. Some JobSpy sites may use it. If a cloud image is minimal, ensure Playwright deps are installed and enough memory is available for Chromium.

---

## 9. Customization for Your Friend

They’ll want to tailor job searches and scoring:

- **`config.py`:**  
  - `USER_PROFILE_SUMMARY`: their background, target roles, location.  
  - `JOBSPY_QUERIES`, `JOBSPY_SITES`, `JOBSPY_RESULTS_PER_QUERY`: queries and sites.  
  - `GREENHOUSE_TARGETS` (and similar) if using ATS scrapers.
- **`config/scoring_weights.yaml`:** Vertical weights, reject/shortlist thresholds, role-fit rules.
- **`config/golden_leads.yaml`:** If used by scoring or scripts, adjust to their “ideal” companies or roles.

Document these in a short “Setup” section so they know what to edit.

---

## 10. Summary

| Goal | Approach |
|------|----------|
| **Package** | Minimal: Agent 1 + core deps + config. Extended: multi-scraper pipeline + optional UI. |
| **Configure** | Add `.env.template`; set at least one LLM key and optional `DATABASE_URL`. |
| **Run locally** | venv + `init_db` → `agent1_job_scraper.py` or `run_quick_wins.sh`; optionally `streamlit run ui_streamlit.py`. |
| **Run in cloud** | Docker (existing Dockerfile) on a VPS or PaaS; Postgres recommended; run scraper on cron or scheduler. |
| **Before sharing** | Fix `Company` import, `fit_score_boost` vs `vertical_score_boost`, `DEBUG_DIR`, and scheduler `run_agent1_scraper` vs `run_agent1_parallel`. `.env.template` is already in the repo. |

Once those small fixes and the template are in place, your friend can run the job scraper locally or in the cloud with minimal friction.

---

## 11. Multi-tenant: share your instance with a friend

If your friend is **not technical**, you can run the app on **your machine** and give them **browser access** instead of packaging for them. See **[MULTI_TENANT_ACCESS.md](MULTI_TENANT_ACCESS.md)** for:

- Running `migrate_multitenant.py` and **Sync jobs to tenants**
- **Viewing as** Bent vs Friend and the **📋 My Shortlist** tab
- Exposing the UI via **ngrok** or **Cloudflare Tunnel** and sharing the URL

They use **My Shortlist** only; you keep **Cockpit** and the full pipeline.
