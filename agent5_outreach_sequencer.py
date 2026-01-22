import logging
import config
from database import SessionLocal
from models import Contact, ProactiveOutreach, Company
from utils import call_llm, parse_json_from_llm
from datetime import datetime, timedelta
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OutreachSequencerAgent:
    """
    Agent 5: Manages personal follow-up sequences for outreach contacts.
    """
    
    FOLLOWUP_SCHEDULE = {
        0: 0,    # Intro
        1: 4,    # Follow-up 1
        2: 10,   # Follow-up 2
    }

    def run(self):
        db = SessionLocal()
        try:
            self.sync_contact_states(db)
            self.generate_followup_tasks(db)
        finally:
            db.close()

    def sync_contact_states(self, db):
        # We look for outreach items that are 'sent' but the contact isn't updated to 'no_response' yet
        sent_outreach = db.query(ProactiveOutreach).filter(
            ProactiveOutreach.status == 'sent',
            ProactiveOutreach.contact_id != None
        ).all()
        
        logger.info(f"📊 Found {len(sent_outreach)} sent outreach items.")
        for o in sent_outreach:
            contact = db.query(Contact).filter(Contact.id == o.contact_id).first()
            if not contact: continue
            
            # Update contact state to 'no_response' (waiting) and set the next check date
            if contact.status != 'no_response' or contact.last_contacted_at != o.sent_at:
                logger.info(f"📈 Updating state for {contact.name}: Sent {o.outreach_type}")
                contact.status = 'no_response'
                contact.last_contacted_at = o.sent_at
                
                # Increment stage IF this was a sent item for that stage or the initial
                # To be simple: if sent_o is 'intro', next is followup_1
                if o.outreach_type == 'intro': contact.followup_stage = 1
                elif 'followup_' in o.outreach_type:
                    try: contact.followup_stage = int(o.outreach_type.split('_')[-1]) + 1
                    except: contact.followup_stage += 1
                
                days_wait = self.FOLLOWUP_SCHEDULE.get(contact.followup_stage, 30)
                contact.next_followup_due = (o.sent_at or datetime.now()) + timedelta(days=days_wait)
                db.commit()

    def generate_followup_tasks(self, db):
        now = datetime.now()
        # Contacts who haven't replied and are due for the next touch
        due_contacts = db.query(Contact).filter(
            Contact.status == 'no_response',
            Contact.next_followup_due <= now,
            Contact.followup_stage > 0,
            Contact.followup_stage < 3
        ).all()
        
        logger.info(f"⏳ Checking {len(due_contacts)} contacts due for follow-up...")
        for contact in due_contacts:
            # Don't duplicate queued follow-ups
            existing_task = db.query(ProactiveOutreach).filter(
                ProactiveOutreach.contact_id == contact.id,
                ProactiveOutreach.status == 'queued'
            ).first()
            if existing_task: continue
            self.create_followup_draft(db, contact)

    def create_followup_draft(self, db, contact):
        company = db.query(Company).filter(Company.id == contact.company_id).first()
        stage = contact.followup_stage
        
        logger.info(f"✍️ Generating Follow-up {stage} for {contact.name} @ {company.name}")
        prompt = f"""
        Generate a follow-up message in JSON format.
        Target: {contact.name} ({contact.title}) at {company.name}.
        Stage: Follow-up #{stage}.
        Recipient Role: {contact.role_type}.
        
        Return JSON structure:
        {{
          "draft_email": "Short, persistent but professional follow-up",
          "outreach_angle": "Reason for follow-up"
        }}
        """
        
        try:
            resp = call_llm(prompt, response_format="json")
            analysis = parse_json_from_llm(resp)
            if not isinstance(analysis, dict):
                logger.error(f"Invalid LLM response format: {analysis}")
                return

            outreach = ProactiveOutreach(
                id=str(uuid.uuid4()),
                company_id=company.id,
                contact_id=contact.id,
                outreach_type=f'followup_{stage}',
                signal_summary=f"Follow-up {stage} sequence",
                fit_explanation=analysis.get('outreach_angle', "Scheduled follow-up"),
                draft_email=analysis.get('draft_email'),
                priority_score=90,
                status='queued'
            )
            db.add(outreach)
            db.commit()
            logger.info(f"✅ Follow-up {stage} queued for {contact.name}")
        except Exception as e:
            logger.error(f"Error creating follow-up draft: {e}")

if __name__ == "__main__":
    agent = OutreachSequencerAgent()
    agent.run()
