"""
Ensure every Job with a JobScore has JobTenant rows for all tenants (same score/status).
Run after scrape+score, or via UI "Sync jobs to tenants". Safe to run repeatedly.
"""
from database import SessionLocal
from models import Job, JobScore, JobTenant, Tenant
import logging

logger = logging.getLogger(__name__)


def sync_job_tenant():
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        if not tenants:
            logger.warning("No tenants found. Run migrate_multitenant.py first.")
            return 0
        jobs = db.query(Job).filter(Job.status.in_(["scored", "shortlisted"])).all()
        added = 0
        for j in jobs:
            js = (
                db.query(JobScore)
                .filter(JobScore.job_id == j.id)
                .order_by(JobScore.created_at.desc())
                .first()
            )
            score = js.overall_score if js else 0
            for t in tenants:
                existing = (
                    db.query(JobTenant)
                    .filter(JobTenant.job_id == j.id, JobTenant.tenant_id == t.id)
                    .first()
                )
                if not existing:
                    db.add(
                        JobTenant(
                            job_id=j.id,
                            tenant_id=t.id,
                            status=j.status,
                            overall_score=score,
                            notes=js.notes if js else None,
                        )
                    )
                    added += 1
        db.commit()
        logger.info("Synced %d JobTenant rows for %d jobs across %d tenants", added, len(jobs), len(tenants))
        return added
    except Exception as e:
        logger.exception("sync_job_tenant failed: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_job_tenant()
