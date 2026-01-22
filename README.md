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
