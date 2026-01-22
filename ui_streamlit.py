import streamlit as st
import pandas as pd
from database import SessionLocal
from models import Job, Company, ProactiveOutreach, Contact
from sqlalchemy import desc, case
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
import urllib.parse
import sys
import uuid

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
FROM_EMAIL = "bent@freeboard-advisory.com"

# Page Setup - maximizing real estate for ultra-wide screens
st.set_page_config(page_title="Strategic Outreach Control", layout="wide", initial_sidebar_state="collapsed")

# Functional CSS
st.markdown("""
<style>
    .stApp { background-color: #f6f8fa; color: #24292e; }
    [data-testid="column"] { padding: 0.5rem; }
    
    /* Panel Containers */
    .stTextArea textarea {
        background-color: #fdfdfd !important;
        color: #24292e !important;
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 1.05em;
        line-height: 1.4;
    }
    
    /* Typography */
    .lead-title { font-weight: 600; font-size: 1.1em; color: #0366d6; margin-bottom: 2px; }
    .lead-meta { font-size: 0.8em; color: #586069; margin-bottom: 10px; }
    
    /* Card Styles */
    .master-item {
        padding: 10px;
        border-radius: 4px;
        border: 1px solid #e1e4e8;
        margin-bottom: 5px;
        background: white;
        cursor: pointer;
    }
    
    /* Action buttons */
    .stButton>button { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def build_mailto(to_email: str, subject: str, body: str) -> str:
    """Build a mailto: link with proper URL encoding."""
    return (
        "mailto:" + urllib.parse.quote(to_email) +
        "?subject=" + urllib.parse.quote(subject) +
        "&body=" + urllib.parse.quote(body)
    )


def get_daily_queue(session, include_jobs=True, include_signals=True, include_followups=True):
    """
    Get outreach items due today or overdue, ordered by type and score.
    
    Priority:
    1. job_intro (score 0)
    2. signal_intro (score 1)
    3. followup_* (score 2)
    4. everything else (score 3)
    
    Then by fit_score DESC, then created_at DESC
    """
    now = datetime.utcnow()
    
    query = (
        session.query(ProactiveOutreach)
        .options(
            joinedload(ProactiveOutreach.company),
            joinedload(ProactiveOutreach.contact),
            joinedload(ProactiveOutreach.job)
        )
        .filter(ProactiveOutreach.status.in_(["queued", "snoozed"]))
        .filter(
            (ProactiveOutreach.next_action_at <= now) | 
            (ProactiveOutreach.next_action_at.is_(None))
        )
    )
    
    # Build type filter based on booleans
    type_filters = []
    if include_jobs:
        type_filters.append(ProactiveOutreach.outreach_type == "job_intro")
    if include_signals:
        type_filters.append(ProactiveOutreach.outreach_type == "signal_intro")
    if include_followups:
        type_filters.append(ProactiveOutreach.outreach_type.like("followup%"))
    
    # If any filters selected, apply OR condition
    if type_filters:
        from sqlalchemy import or_
        query = query.filter(or_(*type_filters))
    
    # Order by type priority, then fit_score, then created_at
    query = query.order_by(
        case(
            (ProactiveOutreach.outreach_type == "job_intro", 0),
            (ProactiveOutreach.outreach_type == "signal_intro", 1),
            (ProactiveOutreach.outreach_type.like("followup%"), 2),
            else_=3
        ),
        ProactiveOutreach.fit_score.desc().nullslast(),
        ProactiveOutreach.created_at.desc()
    )
    
    return query.all()


def handle_sent(session, outreach_id: str):
    """
    Mark as sent and create follow-up if this is an intro.
    
    - status = "sent"
    - sent_at = now
    - If outreach_type is an intro, create followup_1 due in 4 days
    """
    o = session.get(ProactiveOutreach, outreach_id)
    if not o:
        return
    
    now = datetime.utcnow()
    o.status = "sent"
    o.sent_at = now
    
    # Create follow-up for intro types
    if o.outreach_type in ("job_intro", "signal_intro"):
        followup = ProactiveOutreach(
            id=str(uuid.uuid4()),
            job_id=o.job_id,
            company_id=o.company_id,
            contact_id=o.contact_id,
            outreach_type="followup_1",
            status="queued",
            next_action_at=now + timedelta(days=4),
            fit_score=o.fit_score,
            priority_score=o.priority_score,
            signal_summary=f"Follow-up to: {o.signal_summary}" if o.signal_summary else "Follow-up",
            fit_explanation=o.fit_explanation,
            draft_email=""  # User will write follow-up
        )
        session.add(followup)
    
    session.commit()


def handle_replied(session, outreach_id: str):
    """Mark as replied - no follow-up needed."""
    o = session.get(ProactiveOutreach, outreach_id)
    if not o:
        return
    
    o.status = "replied"
    o.next_action_at = None
    session.commit()


def handle_dismiss(session, outreach_id: str):
    """Dismiss this outreach item."""
    o = session.get(ProactiveOutreach, outreach_id)
    if not o:
        return
    
    o.status = "dismissed"
    o.next_action_at = None
    session.commit()


def categorize_lead(o):
    """Categorize lead for display."""
    otype = (o.outreach_type or "").lower()
    if otype == "job_intro":
        return "📋 JOB"
    elif otype == "signal_intro":
        return "🔥 SIGNAL"
    elif "followup" in otype:
        return "🔔 F/UP"
    return "📧 OTHER"


def get_default_subject(o):
    """Generate default email subject based on outreach type."""
    company_name = o.company.name if o.company else "your company"
    
    if o.job and o.job.title:
        return f"Quick note re: {o.job.title} at {company_name}"
    elif o.outreach_type and "followup" in o.outreach_type.lower():
        return f"Following up - {company_name}"
    else:
        return f"Connecting re: {company_name}"


# ---------------------------------------------------------------------------
# MAIN UI
# ---------------------------------------------------------------------------
st.title("📂 Outreach Control Center")

# Open long-lived session for the whole run
db = SessionLocal()

try:
    # =========================================================================
    # 3-PANEL LAYOUT with filters at top
    # =========================================================================
    
    # Filter Bar
    st.markdown("---")
    fcol1, fcol2, fcol3, fcol4 = st.columns([1, 1, 1, 2])
    with fcol1:
        show_jobs = st.checkbox("📋 Jobs", value=True)
    with fcol2:
        show_signals = st.checkbox("🔥 Signals", value=True)
    with fcol3:
        show_fups = st.checkbox("🔔 Follow-ups", value=True)
    with fcol4:
        if st.button("🔄 Sync Leads"):
            import subprocess
            subprocess.run([sys.executable, "sync_leads.py"])
            st.rerun()
    
    st.markdown("---")
    
    # Get filtered queue using the proper query function
    queue_items = get_daily_queue(db, include_jobs=show_jobs, include_signals=show_signals, include_followups=show_fups)
    
    if not queue_items:
        st.info("🎉 Queue is empty! Check filters or sync new leads.")
    else:
        # 3-PANEL LAYOUT: Queue (1/4) | Email Editor (1/2) | Strategy+Company (1/4)
        col_queue, col_email, col_context = st.columns([1, 2, 1])
        
        # --- LEFT COLUMN: QUEUE LIST ---
        with col_queue:
            st.markdown(f"### 📋 Queue ({len(queue_items)})")
            
            for item in queue_items:
                cat = categorize_lead(item)
                co_name = item.company.name if item.company else "Unknown"
                score_display = f"({item.fit_score})" if item.fit_score else ""
                
                label = f"{cat} {score_display}\n{co_name}"
                if st.button(label, key=f"sel_{item.id}", use_container_width=True):
                    st.session_state.selected_lead_id = item.id
                    st.rerun()
        
        # Get selected item (default to first in queue)
        curr_id = st.session_state.get('selected_lead_id', queue_items[0].id)
        
        # Find the object in current session (with eager loads)
        selected = db.query(ProactiveOutreach).options(
            joinedload(ProactiveOutreach.company),
            joinedload(ProactiveOutreach.contact),
            joinedload(ProactiveOutreach.job)
        ).filter(ProactiveOutreach.id == curr_id).first()
        
        # If selected item no longer exists in queue, pick first
        if not selected:
            selected = queue_items[0]
            st.session_state.selected_lead_id = selected.id
        
        # --- MIDDLE COLUMN: EMAIL EDITOR + ACTIONS ---
        with col_email:
            st.markdown(f"### 📧 Draft: {selected.company.name if selected.company else 'Outreach'}")
            
            # Contact info
            if selected.contact:
                st.markdown(f"**To:** {selected.contact.name} ({selected.contact.title})")
                to_email = selected.contact.email
                if to_email:
                    st.caption(f"📬 {to_email}")
                else:
                    st.warning("⚠️ No email found for this contact yet.")
            else:
                st.warning("⚠️ No contact assigned to this outreach.")
                to_email = None
            
            # Job context if available
            if selected.job:
                st.info(f"📋 **Role:** {selected.job.title}")
            
            # Email draft editor
            draft_val = st.text_area(
                "Finalized Message", 
                value=selected.draft_email or "", 
                height=400, 
                key=f"txt_{selected.id}"
            )
            
            # Mail button with mailto link
            subject = get_default_subject(selected)
            
            if to_email:
                mailto_link = build_mailto(to_email, subject, draft_val)
                st.markdown(f'''
                    <a href="{mailto_link}" target="_blank" style="text-decoration: none;">
                        <button style="width: 100%; height: 55px; background-color: #0366d6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 1.2em; margin-bottom: 15px;">
                            📩 Open in Mail Client ({FROM_EMAIL})
                        </button>
                    </a>
                ''', unsafe_allow_html=True)
            else:
                st.button("📩 Open in Mail Client (No email)", disabled=True, use_container_width=True)
            
            st.markdown("### Actions")
            
            # --- ACTION BUTTONS ---
            act1, act2, act3 = st.columns(3)
            
            with act1:
                if st.button("🚀 Sent", key=f"btn_sent_{selected.id}", use_container_width=True, type="primary"):
                    handle_sent(db, selected.id)
                    st.success("Marked as sent! Follow-up created." if selected.outreach_type in ("job_intro", "signal_intro") else "Marked as sent!")
                    st.rerun()
            
            with act2:
                if st.button("✅ Replied", key=f"btn_replied_{selected.id}", use_container_width=True):
                    handle_replied(db, selected.id)
                    st.success("Marked as replied!")
                    st.rerun()
            
            with act3:
                if st.button("❌ Dismiss", key=f"btn_dismiss_{selected.id}", use_container_width=True):
                    handle_dismiss(db, selected.id)
                    st.warning("Dismissed!")
                    st.rerun()
        
        # --- RIGHT COLUMN: STRATEGY + COMPANY (STACKED) ---
        with col_context:
            # Strategy box (top)
            st.markdown("### 🧠 Strategy")
            if selected.fit_explanation:
                st.info(selected.fit_explanation)
            else:
                st.caption("No strategy notes.")
            
            if selected.signal_summary:
                st.markdown("**Signal:**")
                st.caption(selected.signal_summary)
            
            if selected.contact:
                st.markdown(f"**Contact Role:** {selected.contact.role_type or 'Unknown'}")
                if selected.contact.linkedin_url:
                    st.markdown(f"[🔗 LinkedIn]({selected.contact.linkedin_url})")
            
            st.markdown("---")
            
            # Company box (bottom)
            st.markdown("### 🏢 Company")
            if selected.company:
                st.markdown(f"**Name:** {selected.company.name}")
                st.markdown(f"**Vertical:** {selected.company.vertical or 'N/A'}")
                st.markdown(f"**Employees:** {selected.company.employee_count or 'N/A'}")
                st.markdown(f"**HQ:** {selected.company.hq_location or 'N/A'}")
                st.markdown(f"**Fit Score:** {selected.company.fit_score or 'N/A'}")
                
                links = []
                if selected.company.linkedin_url:
                    links.append(f"[LinkedIn]({selected.company.linkedin_url})")
                if selected.company.crunchbase_url:
                    links.append(f"[Crunchbase]({selected.company.crunchbase_url})")
                if links:
                    st.markdown(" | ".join(links))
            else:
                st.caption("No company data.")

    # =========================================================================
    # HISTORY SECTION (Collapsible)
    # =========================================================================
    with st.expander("📜 Outreach History"):
        history = db.query(ProactiveOutreach).options(
            joinedload(ProactiveOutreach.company),
            joinedload(ProactiveOutreach.contact)
        ).filter(ProactiveOutreach.status.notin_(["queued", "snoozed"])).order_by(desc(ProactiveOutreach.sent_at)).limit(50).all()
        
        if not history:
            st.info("No recorded history.")
        else:
            hist_data = []
            for h in history:
                hist_data.append({
                    "Status": h.status.upper() if h.status else "N/A",
                    "Company": h.company.name if h.company else "Unknown",
                    "Contact": h.contact.name if h.contact else "N/A",
                    "Type": h.outreach_type or "N/A",
                    "Sent": h.sent_at.strftime('%Y-%m-%d %H:%M') if h.sent_at else "-"
                })
            st.dataframe(pd.DataFrame(hist_data), use_container_width=True, hide_index=True)

finally:
    db.close()
