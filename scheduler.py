from apscheduler.schedulers.blocking import BlockingScheduler
from agent1_job_scraper import run_agent1_scraper
from agent2_signal_monitor import run_agent2_monitor
from agent3_universe_builder import build_initial_universe
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler()

# Agent 1: every 6 hours
scheduler.add_job(run_agent1_scraper, 'interval', hours=6, id='job_scraper')

# Agent 2: daily at 6am
scheduler.add_job(run_agent2_monitor, 'cron', hour=6, id='signal_monitor')

# Agent 3: Weekly universe refresh
# scheduler.add_job(build_initial_universe, 'cron', day_of_week='sun', hour=2, id='universe_refresher')

logger.info("Starting scheduler...")
try:
    scheduler.start()
except (KeyboardInterrupt, SystemExit):
    pass
