from database import engine, SessionLocal
from models import ProactiveOutreach, Base
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_schema():
    """
    1. Add 'insights' column to proactive_outreach if missing.
    """
    session = SessionLocal()
    try:
        # Check if column exists
        result = session.execute(text("PRAGMA table_info(proactive_outreach)"))
        columns = [row[1] for row in result.fetchall()]
        
        if 'insights' not in columns:
            logger.info("Adding 'insights' column to proactive_outreach...")
            session.execute(text("ALTER TABLE proactive_outreach ADD COLUMN insights TEXT"))
            session.commit()
        else:
            logger.info("'insights' column already exists.")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    migrate_schema()
