from sqlalchemy import Column, String, Integer, Boolean, Numeric, DateTime, ForeignKey, Enum, JSON, Text
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Company(Base):
    __tablename__ = 'companies'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), unique=True)
    domain = Column(String(255), nullable=True)
    vertical = Column(String(100)) # e.g. 'healthcare', 'fintech', 'denver_saas'
    stage = Column(String(100))
    funding_total = Column(Numeric)
    employee_count = Column(Integer)
    hq_location = Column(String(255))
    is_bootstrapped = Column(Boolean, default=False)
    profitability_signal = Column(Text)
    linkedin_url = Column(String(500))
    crunchbase_url = Column(String(500))
    fit_score = Column(Integer)
    monitoring_status = Column(Enum('active', 'archived', 'low_priority', name='monitoring_status'), default='active')
    last_signal_date = Column(DateTime)
    signal_score_30d = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    raw_data = Column(JSON)
    
    signals = relationship("CompanySignal", back_populates="company")
    jobs = relationship("Job", back_populates="company")
    contacts = relationship("Contact", back_populates="company")
    applications = relationship("Application", back_populates="company")

class CompanySignal(Base):
    __tablename__ = 'company_signals'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id'))
    signal_type = Column(String(100)) # e.g. 'funding', 'hiring', 'expansion'
    signal_date = Column(DateTime)
    signal_text = Column(Text)
    score = Column(Integer)
    source_url = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    
    company = relationship("Company", back_populates="signals")

class Job(Base):
    __tablename__ = 'jobs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=True)
    source = Column(String(100))
    title = Column(String(500))
    company_name = Column(String(255))
    location = Column(String(255))
    is_remote = Column(Boolean)
    is_local = Column(Boolean)
    url = Column(String(1000))
    date_posted = Column(DateTime)
    description = Column(Text)
    raw_data = Column(JSON)
    dedupe_key = Column(String(255), unique=True)
    status = Column(Enum('new', 'scored', 'shortlisted', 'applied', 'interview', 'rejected', 'archived', name='job_status'), default='new')
    vertical = Column(String(100))
    vertical_score_boost = Column(Integer, default=0)
    application_method = Column(String(100))
    form_complexity = Column(String(100))
    local_bonus_applied = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_seen_at = Column(DateTime, server_default=func.now())
    source_urls = Column(JSON)
    
    company = relationship("Company", back_populates="jobs")
    scores = relationship("JobScore", back_populates="job")
    job_tenants = relationship("JobTenant", back_populates="job")

class Tenant(Base):
    """Multi-tenant: each user (e.g. you, a friend) has isolated job shortlist / profile."""
    __tablename__ = 'tenants'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), unique=True)
    slug = Column(String(100), unique=True)
    profile_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    job_tenants = relationship("JobTenant", back_populates="tenant")

class JobTenant(Base):
    """Per-tenant job score and status. Same job can be shortlisted for one tenant, rejected for another."""
    __tablename__ = 'job_tenant'
    job_id = Column(String(36), ForeignKey('jobs.id'), primary_key=True)
    tenant_id = Column(String(36), ForeignKey('tenants.id'), primary_key=True)
    status = Column(String(50), default='new')  # new, scored, shortlisted, rejected, applied, archived
    overall_score = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    job = relationship("Job", back_populates="job_tenants")
    tenant = relationship("Tenant", back_populates="job_tenants")

class JobScore(Base):
    __tablename__ = 'job_scores'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey('jobs.id'))
    overall_score = Column(Integer)
    seniority_score = Column(Integer)
    healthcare_score = Column(Integer)
    payer_score = Column(Integer)
    saas_score = Column(Integer)
    deal_size_alignment = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    
    job = relationship("Job", back_populates="scores")

class Contact(Base):
    __tablename__ = 'contacts'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id'))
    name = Column(String(255))
    title = Column(String(255))
    email = Column(String(255))
    linkedin_url = Column(String(500))
    role_type = Column(String(100)) # e.g. 'hiring_manager', 'executive'
    apollo_id = Column(String(100))
    confidence_score = Column(Integer)
    
    # Sequence Tracking
    status = Column(String(50), default='new') # new, lead, emailed, no_response, replied, meeting, closed
    followup_stage = Column(Integer, default=0) # 0: intro, 1: followup1, 2: followup2
    last_contacted_at = Column(DateTime)
    next_followup_due = Column(DateTime)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    company = relationship("Company", back_populates="contacts")

class Application(Base):
    __tablename__ = 'applications'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=True)
    company_id = Column(String(36), ForeignKey('companies.id'))
    contact_id = Column(String(36), ForeignKey('contacts.id'), nullable=True)
    application_type = Column(String(100))
    resume_version = Column(String(255))
    cover_note = Column(Text)
    outreach_email_sent = Column(Boolean, default=False)
    outreach_email_body = Column(Text)
    application_method = Column(String(100))
    ats_submitted = Column(Boolean, default=False)
    submitted_at = Column(DateTime)
    status = Column(String(100))
    response_date = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    company = relationship("Company", back_populates="applications")

class ProactiveOutreach(Base):
    __tablename__ = 'proactive_outreach'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id'))
    contact_id = Column(String(36), ForeignKey('contacts.id'))
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=True)  # Link to job if job-based outreach
    outreach_type = Column(String(50), default='job_intro')  # job_intro, signal_intro, followup_1, followup_2
    signal_summary = Column(Text)
    fit_explanation = Column(Text)
    
    # LEGACY: Council insights and draft (deprecated, use ds_* and px_* fields)
    insights = Column(Text, nullable=True)  # Markdown from Council of Agents
    draft_email = Column(Text, nullable=True)
    
    # V2 PIPELINE: DeepSeek stage (local analysis + draft)
    ds_wedge = Column(String, nullable=True)  # e.g., "Value-Based Care"
    ds_rationale = Column(Text, nullable=True)  # Why this wedge
    ds_key_points = Column(JSON, nullable=True)  # List of proof points
    ds_raw_draft = Column(Text, nullable=True)  # First-pass email
    
    # V2 PIPELINE: Perplexity stage (web-grounded finalization)
    px_final_email = Column(Text, nullable=True)  # Send-ready email
    px_factual_flags = Column(JSON, nullable=True)  # List of unresolved issues
    px_confidence = Column(Numeric, nullable=True)  # 0-1 confidence score
    px_citations = Column(JSON, nullable=True)  # Optional structured citations
    
    # Metadata for traceability (copied from Job or Signals)
    job_url = Column(String(1000), nullable=True)
    job_source = Column(String(100), nullable=True)
    job_location = Column(String(255), nullable=True)
    job_snippet = Column(Text, nullable=True)
    role_title = Column(String(255), nullable=True)
    
    lead_type = Column(String(50), nullable=True)  # job_posting, signal_only
    test_run_id = Column(String(100), nullable=True) # For golden set isolation
    test_scores = Column(JSON, nullable=True) # { "v1": 85, "v2": 90 }
    priority_score = Column(Integer)
    fit_score = Column(Integer, default=0)  # Copied from job/company for queue ordering
    status = Column(String(100), default='queued')  # queued, snoozed, sent, replied, dismissed
    sent_at = Column(DateTime)
    sent_from_address = Column(String(255), nullable=True)
    mailgun_message_id = Column(String(255), nullable=True)
    next_action_at = Column(DateTime, nullable=True)  # When this item becomes actionable
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    company = relationship("Company", foreign_keys=[company_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
    job = relationship("Job", foreign_keys=[job_id])

class LeadCategorizationAudit(Base):
    __tablename__ = 'lead_categorization_audit'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name = Column(String(255))
    role_title = Column(String(500), nullable=True)
    job_url = Column(String(1000), nullable=True)
    signal_source = Column(String(100)) # job_scraper, signal_monitor, lead_sync
    job_posting_detected = Column(Boolean, default=False)
    signal_only_detected = Column(Boolean, default=False)
    final_lead_type = Column(String(50))
    timestamp = Column(DateTime, server_default=func.now())

class GoldenLead(Base):
    __tablename__ = 'golden_leads'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name = Column(String(255))
    vertical = Column(String(100))
    location = Column(String(255), nullable=True)
    expected_fit_tier = Column(String(20)) # high, medium, low
    expected_lead_type = Column(String(50)) # job_posting, signal_only
    is_local = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class CandidateGoldenLead(Base):
    __tablename__ = 'candidate_golden_leads'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name = Column(String(255))
    vertical = Column(String(100))
    location = Column(String(255), nullable=True)
    actual_fit_score = Column(Integer)
    actual_lead_type = Column(String(50))
    reason_flagged = Column(Text) # "High mismatch", "Suspicious vertical", etc.
    source_outreach_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class DiscoveryCandidate(Base):
    """Unvalidated companies from news. Lifecycle: discovered → scored | rejected → promoted (Stage 3 only)."""
    __tablename__ = "discovery_candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name = Column(String(255), nullable=False, index=True)
    context = Column(Text, nullable=True)  # headline/snippet; use as context_summary in Stage 2
    source_url = Column(String(500), nullable=True)
    source_query = Column(String(500), nullable=True)
    prelim_vertical = Column(String(100), nullable=True)  # from cheap Stage-1 hint
    preliminary_fit_score = Column(Integer, default=0)  # 0–100; refreshed in Stage 2 by score_candidate
    discovery_rank = Column(Integer, nullable=True)       # 1=best from ranked extraction; used for ordering
    discovery_score = Column(Integer, default=0)         # pre-sieve heuristic: Series/payer/employer boosts
    canonical_company_name = Column(String(255), nullable=True)  # from Stage 1.5 entity resolution
    entity_confidence = Column(Integer, nullable=True)   # 0–100; set by Stage 1.5; <70 → reject
    status = Column(String(50), default="discovered", index=True)  # discovered → scored | rejected → promoted
    rejected_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    scored_at = Column(DateTime, nullable=True)   # set when Stage 2 runs
    promoted_at = Column(DateTime, nullable=True) # set when Stage 3 promotes
    promoted_company_id = Column(String(36), ForeignKey("companies.id"), nullable=True)


class OutboundEmail(Base):
    __tablename__ = 'outbound_emails'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    outreach_id = Column(String(36), ForeignKey('proactive_outreach.id'), nullable=True)
    recipient_email = Column(String(255))
    sender_email = Column(String(255))
    email_type = Column(String(20), default='primary') # primary, audit
    subject = Column(String(255))
    body_text = Column(Text)
    mailgun_message_id = Column(String(255))
    status = Column(String(50), default='sent')
    created_at = Column(DateTime, server_default=func.now())
