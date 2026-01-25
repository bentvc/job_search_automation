import streamlit as st
from streamlit_autorefresh import st_autorefresh
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job, GoldenLead, CandidateGoldenLead, CompanySignal
from datetime import datetime, timedelta
import urllib.parse
import uuid
from mailgun_client import send_email_via_mailgun, choose_sender_address
from export_utility import get_last_export_timestamp
from create_export import run_export_and_transfer
import os
from pipeline_v2 import deepseek_analyze_and_draft, perplexity_finalize, run_v2_pipeline
import config
from scoring import score_lead

st.set_page_config(layout="wide", page_title="Job Search Cockpit")
import pandas as pd
import yaml

# --- CSS STYLING ---
st.markdown("""
<style>
    /* Force Light Theme for critical inputs */
    textarea, input {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
    }
    .fit-score-chip {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 12px;
        margin-right: 8px;
    }
    .fit-score-high {
        background-color: #4CAF50;
        color: white;
    }
    .fit-score-medium {
        background-color: #FF9800;
        color: white;
    }
    .fit-score-low {
        background-color: #9E9E9E;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- PIPELINE WRAPPERS ---
def run_deepseek_stage(outreach, company, contact, job, session):
    try:
        with st.spinner("🧠 DeepSeek analyzing & drafting..."):
            result = deepseek_analyze_and_draft(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                sender_profile=config.USER_PROFILE_SUMMARY
            )
            # Update record
            outreach.ds_wedge = result.get('wedge')
            outreach.ds_rationale = "\n".join(result.get("rationale_bullets", []))
            outreach.ds_key_points = result.get("proof_points", [])
            outreach.ds_raw_draft = result.get("email_draft", "")
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            # Sync session state for the editor
            draft_key = f"draft_text_{outreach.id}"
            st.session_state[draft_key] = outreach.px_final_email or outreach.ds_raw_draft or outreach.draft_email or ""
            
            st.success("✅ DeepSeek analysis complete!")
            st.rerun()
    except Exception as e:
        st.error(f"❌ DeepSeek failed: {e}")

def run_perplexity_stage(outreach, company, contact, job, session):
    try:
        with st.spinner("🌐 Perplexity verifying & finalizing..."):
            # We need the wedge from DeepSeek
            if not outreach.ds_wedge:
                st.error("Missing DeepSeek analysis. Run Stage 1 first.")
                return

            result = perplexity_finalize(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                job_url=outreach.job_url or (job.url if job else None),
                sender_profile=config.USER_PROFILE_SUMMARY,
                ds_wedge=outreach.ds_wedge,
                ds_rationale=outreach.ds_rationale,
                ds_proof_points=outreach.ds_key_points,
                ds_raw_draft=outreach.ds_raw_draft,
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )
            
            # Update record
            outreach.px_final_email = result['px_final_email']
            outreach.px_confidence = result['px_confidence']
            outreach.px_factual_flags = result['px_factual_flags']
            outreach.px_citations = result.get('px_citations')
            outreach.status = "ready" if result['px_confidence'] >= 0.85 and not result['px_factual_flags'] else outreach.status
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            # Sync session state for the editor
            draft_key = f"draft_text_{outreach.id}"
            st.session_state[draft_key] = outreach.px_final_email or outreach.ds_raw_draft or outreach.draft_email or ""
            
            st.success("✅ Perplexity finalization complete!")
            st.rerun()
    except Exception as e:
        st.error(f"❌ Perplexity failed: {e}")

def run_full_v2_pipeline(outreach, company, contact, job, session):
    try:
        with st.spinner("🚀 Running Full V2 Pipeline..."):
            # Stage 1
            ds_result = deepseek_analyze_and_draft(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                sender_profile=config.USER_PROFILE_SUMMARY
            )
            
            # Stage 2
            px_result = perplexity_finalize(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                job_url=outreach.job_url or (job.url if job else None),
                sender_profile=config.USER_PROFILE_SUMMARY,
                ds_wedge=ds_result['wedge'],
                ds_rationale="\n".join(ds_result.get("rationale_bullets", [])),
                ds_proof_points=ds_result.get("proof_points", []),
                ds_raw_draft=ds_result.get("email_draft", ""),
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )
            
            # Update record with ALL data
            outreach.ds_wedge = ds_result['wedge']
            outreach.ds_rationale = "\n".join(ds_result.get("rationale_bullets", []))
            outreach.ds_key_points = ds_result.get("proof_points", [])
            outreach.ds_raw_draft = ds_result.get("email_draft", "")
            
            outreach.px_final_email = px_result['final_email']
            outreach.px_confidence = px_result['confidence']
            outreach.px_factual_flags = px_result['factual_flags']
            outreach.px_citations = px_result.get('citations')
            
            if px_result.get('confidence', 0) >= 0.85 and not px_result.get('factual_flags'):
                outreach.status = "ready"
                
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            # Sync session state for the editor
            draft_key = f"draft_text_{outreach.id}"
            st.session_state[draft_key] = outreach.px_final_email or outreach.ds_raw_draft or outreach.draft_email or ""
            
            st.success("✅ Full V2 Pipeline complete!")
            st.rerun()
    except Exception as e:
        st.error(f"❌ Pipeline failed: {e}")

# --- DB HELPERS ---
def get_session():
    return SessionLocal()

def get_queue(session, filter_types=None):
    query = session.query(ProactiveOutreach).filter(
        ProactiveOutreach.status.in_(['queued', 'snoozed']),
        (ProactiveOutreach.next_action_at <= datetime.utcnow()) | (ProactiveOutreach.next_action_at == None),
        ProactiveOutreach.test_run_id == None
    )
    items = query.all()
    
    if filter_types:
        filtered = []
        for i in items:
            if 'Job Applications' in filter_types and 'job' in i.outreach_type: filtered.append(i)
            elif 'Signal Outreaches' in filter_types and 'signal' in i.outreach_type: filtered.append(i)
            elif 'Follow-ups' in filter_types and 'followup' in i.outreach_type: filtered.append(i)
        items = filtered
    
    def sort_key(x):
        type_priority = 0 if x.lead_type == 'job_posting' else 1 if x.lead_type == 'signal_only' else 2
        score = x.fit_score if x.fit_score is not None else 0
        posted_at = x.job.date_posted if x.job and x.job.date_posted else (x.created_at or datetime.min)
        return (-score, -posted_at.timestamp(), type_priority)
        
    return sorted(items, key=sort_key)

# --- MAIN UI ---
def main():
    st_autorefresh(interval=10000, limit=None, key="cockpit_refresh")
    session = get_session()

    with st.sidebar:
        st.markdown("### 📦 Export Codebase")
        st.caption("💡 Click ⬅️ to collapse sidebar")
        st.markdown("---")

        def _do_export(incremental: bool):
            with st.spinner("Creating archive..."):
                r = run_export_and_transfer(incremental=incremental, auto_scp=True, windows_username="chris")
            if r["error"]: st.error(r["error"])
            else:
                st.success(f"Archived {r['filename']} ({r['size_mb']:.1f}MB)")
                st.session_state["export_path"] = r["path"]
                st.session_state["export_filename"] = r["filename"]
                st.session_state["export_size"] = r["size_mb"]
                st.session_state["export_scp_command"] = r["scp_command"]
                st.session_state["export_scp_success"] = r["scp_success"]

        c1, c2 = st.columns(2)
        with c1:
            if st.button("📦 Full Export", use_container_width=True): _do_export(False)
        with c2:
            if st.button("✨ Incremental", use_container_width=True): _do_export(True)
        
        scp_cmd = st.session_state.get("export_scp_command")
        if scp_cmd:
            with st.expander("🔧 SCP command", expanded=not st.session_state.get("export_scp_success")):
                st.code(scp_cmd, language="bash")

        st.markdown("---")
        st.subheader("⛏️ Mining & Sync")
        if st.button("🔍 Run Quick Scrape", use_container_width=True):
            import subprocess
            with st.status("🚀 Running Scraper...", expanded=True) as status:
                st.write("🔍 Searching LinkedIn & Indeed...")
                process = subprocess.run(["python3", "quick_test_scrape.py", "--quick"], capture_output=True, text=True)
                if process.returncode == 0:
                    status.update(label="✅ Scrape Complete", state="complete", expanded=False)
                    st.toast("Scrape complete!", icon="🔍")
                else:
                    status.update(label="❌ Scrape Failed", state="error", expanded=True)
                    st.error(process.stderr)
            st.rerun()
            
        if st.button("⚡ Fast Sync Pipeline", use_container_width=True, type="primary"):
            import subprocess
            with st.status("⚡ Running Fast Sync...", expanded=True) as status:
                st.write("1️⃣ Scoring...")
                subprocess.run(["python3", "agent1_job_scraper.py", "--test"], capture_output=True)
                st.write("2️⃣ Syncing...")
                subprocess.run(["python3", "sync_leads.py"], capture_output=True)
                status.update(label="✅ Fast Sync Complete", state="complete", expanded=False)
            st.toast("Pipeline synced!", icon="⚡")
            st.rerun()

        st.markdown("---")
        st.subheader("🛠️ Maintenance")
        if st.button("🔄 Rescore Production Leads"):
            import subprocess
            subprocess.run(["python3", "scripts/rescore_production_leads.py"])
            st.success("Re-scored!")
            st.rerun()

    tab_cockpit, tab_test = st.tabs(["🚀 Cockpit", "🧪 Test Scoring"])

    with tab_cockpit:
        col_queue, col_editor, col_insights = st.columns([1, 2, 1], gap="small")

        with col_queue:
            st.header("Inbox")
            filter_options = st.multiselect("Filters:", ['Job Applications', 'Signal Outreaches', 'Follow-ups'], default=['Job Applications', 'Signal Outreaches', 'Follow-ups'])
            queue_items = get_queue(session, filter_options)
            st.caption(f"{len(queue_items)} items due")
            
            if queue_items:
                options_list = []
                for item in queue_items:
                    score = item.fit_score or 0
                    indicator = "🟢" if score >= 80 else "🟡" if score >= 60 else "⚪"
                    icon = "💼" if item.lead_type == 'job_posting' else "📡" if item.lead_type == 'signal_only' else "❓"
                    company_name = item.company.name if item.company else 'Unknown'
                    label = f"{indicator} {score} {icon} {company_name}"
                    
                    posted_at = item.job.date_posted if item.job and item.job.date_posted else item.created_at
                    if posted_at:
                        hours_old = (datetime.utcnow() - posted_at).total_seconds() / 3600
                        if hours_old < 24: label += " 🔥"
                        elif hours_old < 72: label += " 🕒"
                    
                    golden = session.query(GoldenLead).filter(GoldenLead.company_name.ilike(f"%{company_name}%")).first()
                    if golden:
                        exp = golden.expected_fit_tier
                        if (exp == 'high' and score < 60) or (exp == 'medium' and score < 40):
                            label += " 🚩"
                            
                    options_list.append((label, item.id))
                
                options_dict = {label: item_id for label, item_id in options_list}
                selected_label = st.radio("Select Outreach:", options=list(options_dict.keys()), label_visibility="collapsed")
                selected_id = options_dict.get(selected_label)
            else:
                selected_id = None

        if selected_id:
            outreach = session.query(ProactiveOutreach).get(selected_id)
            company = outreach.company
            contact = outreach.contact
            job = session.query(Job).get(outreach.job_id) if outreach.job_id else None

            with col_editor:
                st.subheader(f"{company.name}")
                
                # --- Editor State Management ---
                draft_key = f"draft_text_{outreach.id}"
                if draft_key not in st.session_state:
                    st.session_state[draft_key] = outreach.px_final_email or outreach.ds_raw_draft or outreach.draft_email or ""
                
                # 1. Strategy Context (Moved to Top & Expanded)
                with st.expander("🎯 Strategy & Fit", expanded=True):
                    # Job traceability in header
                    if outreach.role_title:
                        if outreach.job_url:
                            st.markdown(f"### Lead: [{outreach.role_title}]({outreach.job_url})")
                        else:
                            st.markdown(f"### Lead: {outreach.role_title}")
                        
                        age_h = 0
                        posted = outreach.job.date_posted if outreach.job and outreach.job.date_posted else outreach.created_at
                        if posted:
                            age_h = (datetime.utcnow() - posted).total_seconds() / 3600
                        
                        st.caption(f"Source: **{outreach.job_source or 'unknown'}** • Posted **{age_h:.1f}h** ago")
                    
                    st.metric("Fit Score", value=outreach.fit_score)
                    
                    with st.expander("🔍 Scoring Inspector", expanded=False):
                        signals = session.query(CompanySignal).filter(CompanySignal.company_id == outreach.company_id).all()
                        bd = score_lead(company, job=job, signals=signals, return_breakdown=True)
                        st.write("**Components:**")
                        cols = st.columns(2)
                        
                        # Use data directly from outreach if available, fallback to job
                        source = outreach.job_source or (job.source if job else 'unknown')
                        url = outreach.job_url or (job.url if job else None)
                        
                        cols[0].write(f"Vertical: {bd['vertical_score']}")
                        cols[0].write(f"Lead Type: {bd['lead_type_score']}")
                        cols[0].write(f"Location: {bd['location_score']}")
                        
                        if job or outreach.role_title:
                            posted = outreach.job.date_posted if outreach.job and outreach.job.date_posted else (job.date_posted if job else outreach.created_at)
                            age_h = (datetime.utcnow() - posted).total_seconds() / 3600 if posted else 0
                            cols[1].write(f"Recency: {bd['recency_score']} ({age_h:.1f}h)")
                            cols[1].write(f"Source: {source}")
                            if url:
                                cols[1].markdown(f"[Open Posting]({url})")
                        else:
                            cols[1].write(f"Recency: {bd['recency_score']}")
                            
                        cols[1].write(f"Signal: {bd['signal_score']}")
                        cols[1].write(f"Role Adj: {bd['role_adjustment']}")
                        st.divider()
                        st.write(f"**Total: {bd['final_score']}**")
                    
                    if outreach.fit_explanation: st.markdown(f"**Angle:** {outreach.fit_explanation}")
                
                # 2. Job Context Context (New)
                if outreach.job_url or outreach.job_snippet:
                    with st.expander("📄 Job Context", expanded=True):
                        if outreach.job_url:
                            st.markdown(f"**Role:** [{outreach.role_title or 'Link'}]({outreach.job_url})")
                        if outreach.job_location:
                            st.write(f"**Location:** {outreach.job_location}")
                        if outreach.job_snippet:
                            st.write(f"**Summary:** {outreach.job_snippet}...")

                # 3. Email Draft Space
                st.subheader("Draft Email")
                
                if not st.session_state[draft_key]:
                    st.info("💡 Run the V2 Pipeline on the right to generate a researched draft.")
                
                # Render editor with stable key
                new_text = st.text_area(
                    "Draft Editor", 
                    value=st.session_state[draft_key], 
                    height=350, 
                    label_visibility="collapsed", 
                    key=draft_key + "_widget" # Unique widget key to avoid session state conflicts but keep source
                )
                
                # Sync user edits back to session state
                if new_text != st.session_state[draft_key]:
                    st.session_state[draft_key] = new_text

                # 3. Target Info
                with st.expander("Target Info", expanded=False):
                    if contact:
                        st.markdown(f"**{contact.name}** ({contact.title})")
                        st.caption(contact.email)
                    st.markdown(f"**{company.name}** ({company.vertical})")
                    if company.linkedin_url: st.markdown(f"[LinkedIn]({company.linkedin_url})")

                # 4. Evaluation / Golden
                with st.expander("🏆 Evaluation Rules", expanded=False):
                    tier = st.selectbox("Fit Tier", ["high", "medium", "low", "reject"], index=0, key=f"tier_{selected_id}")
                    if st.button("🌟 Promote to Golden", key=f"gold_{selected_id}"):
                        existing = session.query(GoldenLead).filter(GoldenLead.company_name == company.name).first()
                        if existing: existing.expected_fit_tier = tier
                        else:
                            gl = GoldenLead(id=str(uuid.uuid4()), company_name=company.name, vertical=company.vertical, expected_fit_tier=tier, expected_lead_type=outreach.lead_type)
                            session.add(gl)
                        session.commit()
                        st.success("Promoted!")

            with col_insights:
                st.header("Analysis")
                st.markdown("### ⚡ V2 Pipeline")
                btn1, btn2 = st.columns(2)
                with btn1:
                    if st.button("🧠 Stage 1: DeepSeek", key="btn_ds_v2", help="Local analysis (Strategy & Wedge)", use_container_width=True): 
                        run_deepseek_stage(outreach, company, contact, job, session)
                with btn2:
                    # Only enable Stage 2 if Stage 1 is done
                    can_run_px = outreach.ds_wedge is not None
                    if st.button("🌐 Stage 2: Perplexity", key="btn_px_v2", disabled=not can_run_px, help="Web research & Final Draft", use_container_width=True): 
                        run_perplexity_stage(outreach, company, contact, job, session)
                
                if st.button("🚀 Run Full V2 Pipeline", type="primary", key="btn_full_v2", use_container_width=True): 
                    run_full_v2_pipeline(outreach, company, contact, job, session)

                st.divider()
                
                if outreach.ds_wedge:
                    st.markdown(f"**Wedge:** `{outreach.ds_wedge}`")
                    with st.expander("📋 Rationale", expanded=True): 
                        st.markdown(outreach.ds_rationale or "No rationale provided.")
                    
                    ds_key_points = getattr(outreach, "ds_key_points", [])
                    if ds_key_points:
                        with st.expander("✓ Strategy Points", expanded=True):
                            for pt in ds_key_points: st.markdown(f"- {pt}")
                
                if outreach.px_confidence:
                    conf = float(outreach.px_confidence)
                    st.markdown(f"**Research Confidence:** {'🟢' if conf >= 0.85 else '🟡' if conf >= 0.7 else '🔴'} {int(conf*100)}%")
                    
                    if outreach.px_factual_flags:
                        with st.expander("⚠️ Factual Flags", expanded=True):
                            for f in outreach.px_factual_flags: st.warning(f)
                    
                    px_citations = getattr(outreach, "px_citations", [])
                    if px_citations:
                        with st.expander("📚 Citations", expanded=False):
                            for i, cit in enumerate(px_citations, 1): st.caption(f"{i}. {cit}")
                
                if outreach.insights:
                    with st.expander("🧙‍♂️ Legacy Council", expanded=False):
                        st.markdown(outreach.insights)
        else:
            with col_editor: st.info("🎉 Inbox is empty!")

    with tab_test:
        st.header("Validation Audit")
        runs = [r[0] for r in session.query(ProactiveOutreach.test_run_id).filter(ProactiveOutreach.test_run_id != None).distinct().all()]
        selected_run = st.selectbox("Test Run", runs)
        if selected_run:
            leads = session.query(ProactiveOutreach).filter(ProactiveOutreach.test_run_id == selected_run).all()
            st.dataframe(pd.DataFrame([{"Co": l.company.name, "Score": l.fit_score} for l in leads]))

if __name__ == "__main__":
    main()
