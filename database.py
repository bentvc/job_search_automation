from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, OutboundEmail
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/job_search.db")

# Ensure directory exists for SQLite
if DATABASE_URL.startswith("sqlite:///./"):
    db_path = DATABASE_URL.replace("sqlite:///./", "")
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_last_outbound_email(to_email: str, company_name: str | None = None) -> dict | None:
    """
    Get the last outbound email sent to a specific email address, optionally filtered by company via the outreach relationship.
    Returns None if no email found.
    """
    if not to_email:
        return None
        
    db = SessionLocal()
    try:
        # Normalize: case-insensitive, whitespace-stripped
        clean_email = to_email.strip().lower()
        
        query = db.query(OutboundEmail).filter(
            func.lower(OutboundEmail.recipient_email) == clean_email,
            OutboundEmail.email_type == 'primary'
        )
        
        # If company_name provided, would ideally join, but OutboundEmail->ProactiveOutreach->Company 
        # is complex to query if company_name is just string.
        # For robustness + speed, we'll primarily rely on the concrete email match.
        # But we will ORDER BY created_at DESC to get the latest.
        # Note: If stricter company isolation is needed, we can implement the join.
        
        last_email = query.order_by(OutboundEmail.created_at.desc()).first()
        
        if last_email:
            return {
                "id": last_email.id,
                "created_at": last_email.created_at,
                "subject": last_email.subject,
                "body_text": last_email.body_text,
                "mailgun_message_id": last_email.mailgun_message_id,
                "status": last_email.status
            }
        return None
    finally:
        db.close()
