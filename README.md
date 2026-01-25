# Sales Outreach Automation System

A three-agent system to automate discovery and outreach for senior enterprise sales roles.

## Core Agents
- **Agent 1 (Reactive Job Scraper):** Scrapes job boards (Indeed, LinkedIn, etc.), scores roles, identifies hiring managers via Apollo, and drafts outreach.
- **Agent 2 (Proactive Signal Monitor):** Watches target companies for growth signals (funding, leadership) and scores urgency.
- **Agent 3 (Company Universe Builder):** Builds and maintains a master list of target companies from VC portfolios and Crunchbase.

## Tech Stack
- **Backend:** Python, SQLAlchemy, SQLite (or Postgres)
- **Scraping:** JobSpy
- **APIs:** Apollo, Crunchbase
- **LLM:** OpenAI/Anthropic/Gemini
- **UI:** Streamlit

## Export Codebase

### Streamlit UI (localhost)
1. Open the Streamlit dashboard (`streamlit run ui_streamlit.py`)
2. In the sidebar, find **📦 Export Codebase**
3. **🚀 Create Export** — Full summary, then SCP to `C:\Users\chris\Downloads`
4. **🔄 Incremental Export** — Only files changed since last summary, then SCP
5. Use **📥 Download Summary** as fallback if SCP fails; expand **🔧 SCP command** to run manually on Windows

### Command Line
```bash
# Full export, auto SCP to Windows
python create_export.py

# Incremental (changes since last full export)
python create_export.py --incremental

# Skip auto SCP, just show command
python create_export.py --no-auto-scp

# Custom Windows path
python create_export.py --local-path "C:\Users\chris\Documents"
```

### Manual SCP (if auto fails)
Run from Windows PowerShell (paths from script output):

```powershell
scp user@remote:/path/to/summary.md "C:\Users\chris\Downloads\summary.md"
```

**Note:** Full summary excludes databases, logs, cache. Incremental uses `.last_summary_export`; added to `.gitignore`.

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment:
   ```bash
   cp .env.template .env
   # Add your API keys to .env
   ```
3. Initialize Database:
   ```bash
   python3 -c "from database import init_db; init_db()"
   ```
4. Run agents:
   - Initial Universe Build: `python3 agent3_universe_builder.py`
   - Scraper: `python3 agent1_job_scraper.py`
   - Signal Monitor: `python3 agent2_signal_monitor.py`
5. Start UI:
   ```bash
   streamlit run ui_streamlit.py
   ```
6. Start Scheduler:
   ```bash
   python3 scheduler.py
   ```
