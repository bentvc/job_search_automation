"""
Multi-tenant migration: create tenants + job_tenant, seed Bent + Friend, backfill from Job+JobScore.
Run once: python migrate_multitenant.py
"""
from database import engine, SessionLocal, init_db
from models import Base, Tenant, JobTenant, Job, JobScore
import logging
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BENT_PROFILE = """Senior enterprise sales professional with 15+ years in payer/health plan sales. 
Built and led $90M+ books of business selling to Medicaid, Medicare Advantage, and commercial health plans. 
PRIORITY: Revenue-generating roles ONLY (VP Sales, CRO, Head of Sales, Strategic AE). 
Based in Denver, CO; open to remote US roles."""

FRIEND_PROFILE = """Job seeker; open to roles matching your background. 
Edit your profile in the app (future) or via DB for personalized scoring."""


def run():
    init_db()
    session = SessionLocal()
    try:
        # Create only new multi-tenant tables if missing
        Base.metadata.create_all(
            bind=engine,
            tables=[Tenant.__table__, JobTenant.__table__],
        )

        bent = session.query(Tenant).filter(Tenant.slug == "bent").first()
        if not bent:
            bent = Tenant(
                id=str(uuid.uuid4()),
                name="Bent",
                slug="bent",
                profile_summary=BENT_PROFILE,
            )
            session.add(bent)
            session.flush()
            logger.info("Created tenant Bent")
        else:
            logger.info("Tenant Bent already exists")

        friend = session.query(Tenant).filter(Tenant.slug == "friend").first()
        if not friend:
            friend = Tenant(
                id=str(uuid.uuid4()),
                name="Friend",
                slug="friend",
                profile_summary=FRIEND_PROFILE,
            )
            session.add(friend)
            session.flush()
            logger.info("Created tenant Friend")
        else:
            logger.info("Tenant Friend already exists")

        session.commit()
        session.refresh(bent)
        session.refresh(friend)

        # Backfill JobTenant from Job + JobScore for jobs with status scored/shortlisted
        jobs = session.query(Job).filter(Job.status.in_(["scored", "shortlisted"])).all()
        added = 0
        for j in jobs:
            js = (
                session.query(JobScore)
                .filter(JobScore.job_id == j.id)
                .order_by(JobScore.created_at.desc())
                .first()
            )
            score = js.overall_score if js else 0
            for t in [bent, friend]:
                existing = (
                    session.query(JobTenant)
                    .filter(JobTenant.job_id == j.id, JobTenant.tenant_id == t.id)
                    .first()
                )
                if not existing:
                    session.add(
                        JobTenant(
                            job_id=j.id,
                            tenant_id=t.id,
                            status=j.status,
                            overall_score=score,
                            notes=js.notes if js else None,
                        )
                    )
                    added += 1
        session.commit()
        logger.info("Backfilled %d JobTenant rows for %d jobs", added, len(jobs))
    except Exception as e:
        logger.exception("Migration failed: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()
