import logging
import config
from database import SessionLocal
from models import Job, Company, Contact, ProactiveOutreach
from apollo_client import ApolloClient
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContactFinderAgent:
    """
    Agent 4: Identifies decision makers for high-fit roles and companies using Apollo.
    Includes logic for varying company sizes and role-based prioritization.
    """
    
    def __init__(self):
        self.apollo = ApolloClient()

    def run(self):
        db = SessionLocal()
        try:
            self.find_contacts_for_jobs(db)
            self.find_contacts_for_outreach(db)
            self.find_contacts_for_top_companies(db)
        finally:
            db.close()

    def find_contacts_for_jobs(self, db):
        jobs = db.query(Job).filter(Job.status == 'shortlisted').all()
        logger.info(f"Checking contacts for {len(jobs)} shortlisted jobs...")
        for job in jobs:
            self.process_company_contacts(db, job.company_name, job.company_id)

    def find_contacts_for_outreach(self, db):
        outreach_items = db.query(ProactiveOutreach).filter(ProactiveOutreach.contact_id == None).all()
        logger.info(f"Finding contacts for {len(outreach_items)} proactive targets...")
        for item in outreach_items:
            company = db.query(Company).filter(Company.id == item.company_id).first()
            if company:
                contact_ids = self.process_company_contacts(db, company.name, company.id)
                if contact_ids:
                    item.contact_id = contact_ids[0]
                    db.commit()

    def find_contacts_for_top_companies(self, db):
        top_companies = db.query(Company).filter(Company.fit_score >= 85).limit(20).all()
        for company in top_companies:
            self.process_company_contacts(db, company.name, company.id)

    def classify_role(self, title):
        title_norm = (title or "").lower().replace("-", " ")
        is_founder = any(x in title_norm for x in ["founder", "ceo", "chief executive officer"])
        is_president = "president" in title_norm and "vice president" not in title_norm and "vp" not in title_norm
        
        if is_founder or is_president:
            return "founder"
        if any(x in title_norm for x in ["cro", "cco", "chief revenue officer", "chief commercial officer", "chief growth officer"]):
            return "c_suite"
        if any(x in title_norm for x in ["sales", "revenue", "partnerships", "growth", "business development"]):
            return "gtm_leader"
        if any(x in title_norm for x in ["recruiter", "talent", "hr"]):
            return "recruiter"
        return "executive"

    def rank_contacts(self, contacts, employee_count):
        if not contacts: return []
        def score_role(contact):
            role = contact['role_type']
            size = employee_count or 0
            if size <= 250:
                if role == "founder": return 100
                if role == "c_suite": return 90
                if role == "gtm_leader": return 80
            else:
                if role == "c_suite": return 100
                if role == "gtm_leader": return 95
                if role == "founder": return 60
            return 40
        for c in contacts:
            c['priority'] = score_role(c)
        return sorted(contacts, key=lambda x: x['priority'], reverse=True)

    def process_company_contacts(self, db, company_name, company_id=None):
        try:
            company = None
            if company_id:
                company = db.query(Company).filter(Company.id == company_id).first()
            if not company:
                company = db.query(Company).filter(Company.name.ilike(company_name)).first()

            if not company or not company.domain:
                logger.info(f"🏢 Searching Apollo for company domain: {company_name}")
                orgs = self.apollo.search_organizations(company_name)
                if orgs:
                    best_org = orgs[0]
                    org_name = best_org.get("name")
                    domain = best_org.get("primary_domain")
                    
                    # Atomic find_or_create to avoid unique constraint errors
                    company = db.query(Company).filter(Company.name == org_name).first()
                    if not company:
                        company = Company(
                            id=str(uuid.uuid4()),
                            name=org_name,
                            domain=domain,
                            vertical='other',
                            fit_score=50,
                            raw_data=best_org,
                            employee_count=best_org.get("estimated_num_employees")
                        )
                        db.add(company)
                    else:
                        company.domain = domain
                        company.employee_count = best_org.get("estimated_num_employees")
                    db.commit()
                    db.refresh(company)
                else:
                    return []

            # Check if we already have contacts
            existing_contacts = db.query(Contact).filter(Contact.company_id == company.id).all()
            if existing_contacts:
                return [c.id for c in existing_contacts]

            titles = config.APOLLO_PRIMARY_GTM_TITLES + config.APOLLO_DOMAIN_GTM_TITLES
            if (company.employee_count or 0) <= 250:
                titles += config.APOLLO_EARLY_STAGE_TITLES

            logger.info(f"🔎 Searching Apollo for leadership at {company.name} ({len(titles)} titles)...")
            apollo_people = self.apollo.search_people(company.domain, titles=titles)
            
            contact_candidates = []
            for p in apollo_people:
                contact_candidates.append({
                    'apollo_id': p.get("id"),
                    'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                    'title': p.get("title"),
                    'email': p.get("email"),
                    'linkedin_url': p.get("linkedin_url"),
                    'role_type': self.classify_role(p.get("title")),
                    'email_status': p.get("email_status")
                })
            
            ranked = self.rank_contacts(contact_candidates, company.employee_count)
            
            saved_ids = []
            for c in ranked:
                if not c['apollo_id']: continue
                existing = db.query(Contact).filter(Contact.apollo_id == c['apollo_id']).first()
                if existing:
                    saved_ids.append(existing.id)
                    continue

                new_contact = Contact(
                    id=str(uuid.uuid4()),
                    company_id=company.id,
                    name=c['name'],
                    title=c['title'],
                    email=c['email'],
                    linkedin_url=c['linkedin_url'],
                    apollo_id=c['apollo_id'],
                    role_type=c['role_type'],
                    confidence_score=c['priority']
                )
                db.add(new_contact)
                db.commit()
                saved_ids.append(new_contact.id)
                
            return saved_ids
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing contacts for {company_name}: {e}")
            return []

if __name__ == "__main__":
    agent = ContactFinderAgent()
    agent.run()
