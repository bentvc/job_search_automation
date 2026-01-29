# Codebase Summary (Incremental)
Date: 2026-01-26 11:47:41
Changes since: 2026-01-26 11:44:00

Project Structure:
====================
job_search_automation/
  ui_streamlit.py

========================================

## File: ui_streamlit.py
```py
import streamlit as st
import logging
logger = logging.getLogger(__name__)
from streamlit_autorefresh import st_autorefresh
from database import SessionLocal, get_last_outbound_email
from models import ProactiveOutreach, Company, Contact, Job, GoldenLead, CandidateGoldenLead, CompanySignal, OutboundEmail
from datetime import datetime, timedelta
import urllib.parse
import uuid
import re
from mailgun_client import send_email_via_mailgun, choose_sender_address, SENDER_ADDRESSES, send_mailgun_test_email
from apollo_client import (
    ApolloClient,
    find_contacts_for_lead,
    _load_enrichment_cache,
    get_enriched_data,
    save_enrichment_cache,
)
from llm_contact_finder import find_contacts_via_perplexity
from export_utility import get_last_export_timestamp
from create_export import run_export_and_transfer
import os
import time
from pipeline_v2 import deepseek_analyze_and_draft, perplexity_finalize, run_v2_pipeline
import config
from scoring import score_lead
from utils.email_safety import sanitize_email_text, validate_send_safe

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
def run_deepseek_stage(outreach, company, contact, job, session, status_placeholder):
    try:
        with status_placeholder.status("🧠 DeepSeek Stage 1: Analyzing...", expanded=True) as status:
            status.write("🔍 Identifying strategic wedge & proof points...")
            result = deepseek_analyze_and_draft(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                sender_profile=config.USER_PROFILE_SUMMARY
            )
            outreach.ds_wedge = result.get('wedge')
            outreach.ds_rationale = "\n".join(result.get("rationale_bullets", []))
            outreach.ds_key_points = result.get("proof_points", [])
            outreach.ds_raw_draft = result.get("email_draft", "")
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            status.update(label="✅ Stage 1: DeepSeek Complete", state="complete", expanded=False)
            time.sleep(0.5)
            
        st.rerun()
    except Exception as e:
        status_placeholder.error(f"❌ DeepSeek failed: {e}")

def run_perplexity_stage(outreach, company, contact, job, session, status_placeholder):
    try:
        # Fallback Wedge if DeepSeek hasn't run
        wedge = outreach.ds_wedge or (f"{company.vertical} Alignment" if company.vertical else "Strategic Alignment")
        
        with status_placeholder.status("🌐 Perplexity Stage 2: Researching...", expanded=True) as status:
            status.write("🔍 Searching the web for company news & hooks...")
            result = perplexity_finalize(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                job_url=outreach.job_url or (job.url if job else None),
                sender_profile=config.USER_PROFILE_SUMMARY,
                ds_wedge=outreach.ds_wedge, # Can be None, pipeline handles it
                ds_rationale=outreach.ds_rationale,
                ds_proof_points=outreach.ds_key_points,
                ds_raw_draft=None, # Don't pass raw draft, let Perplexity start fresh
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )
            
            px_email = result.get('final_email') or result.get('px_final_email')
            
            if not px_email:
                status.update(label="⚠️ Perplexity failed", state="error", expanded=True)
                st.error("No email draft returned.")
                st.json(result)
                return

            outreach.px_final_email = px_email
            outreach.px_confidence = result.get('confidence', 0.5)
            outreach.px_factual_flags = result.get('factual_flags', [])
            outreach.px_citations = result.get('citations', [])
            
            if outreach.px_confidence >= 0.85 and not outreach.px_factual_flags:
                outreach.status = "ready"
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            # FORCE RESET: Delete key so next run re-initializes from DB
            draft_key = f"draft_text_{outreach.id}"
            if draft_key in st.session_state:
                del st.session_state[draft_key]
            
            status.update(label="✅ Perplexity Stage 2 complete", state="complete", expanded=False)
            time.sleep(0.5)
            
        st.rerun()
    except Exception as e:
        status_placeholder.error(f"❌ Perplexity failed: {e}")

def run_full_v2_pipeline(outreach, company, contact, job, session):
    try:
        # Check config for optional DeepSeek stage
        use_deepseek = getattr(config, 'USE_DEEPSEEK_STAGE_1', False)
        
        with st.status("🚀 Running Pipeline...", expanded=True) as status:
            ds_result = {}
            if use_deepseek:
                status.write("🧠 Stage 1: DeepSeek Analysis...")
                ds_result = deepseek_analyze_and_draft(
                    company=company.name if company else "Unknown",
                    role=contact.title if contact and contact.title else "Executive",
                    job_description=job.description if job else "N/A",
                    sender_profile=config.USER_PROFILE_SUMMARY
                )
                # Save strategy only
                outreach.ds_wedge = ds_result.get('wedge')
                outreach.ds_rationale = "\n".join(ds_result.get("rationale_bullets", []))
                outreach.ds_key_points = ds_result.get("proof_points", [])
                outreach.ds_raw_draft = ds_result.get("email_draft", "") # Saved but not used for editor
            
            status.write("🌐 Stage 2: Perplexity Research...")
            px_result = perplexity_finalize(
                company=company.name if company else "Unknown",
                role=contact.title if contact and contact.title else "Executive",
                job_description=job.description if job else "N/A",
                job_url=outreach.job_url or (job.url if job else None),
                sender_profile=config.USER_PROFILE_SUMMARY,
                ds_wedge=outreach.ds_wedge, # Might be from new DS run or existing DB value
                ds_rationale=outreach.ds_rationale,
                ds_proof_points=outreach.ds_key_points,
                ds_raw_draft=None, # Ensure Perplexity generates the text
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )
            
            outreach.px_final_email = px_result.get('final_email') or px_result.get('px_final_email')
            outreach.px_confidence = px_result.get('confidence', 0.5)
            outreach.px_factual_flags = px_result.get('factual_flags', [])
            outreach.px_citations = px_result.get('citations', [])
            
            if not outreach.px_final_email:
                status.update(label="⚠️ Perplexity failed", state="error", expanded=True)
                st.error("No final email returned. Raw response shown below.")
                st.json(px_result)
                return

            if outreach.px_confidence >= 0.85 and not outreach.px_factual_flags:
                outreach.status = "ready"
                
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            session.add(outreach)
            session.commit()
            session.refresh(outreach)
            
            # FORCE RESET: Delete key so next run re-initializes from DB
            draft_key = f"draft_text_{outreach.id}"
            if draft_key in st.session_state:
                del st.session_state[draft_key]
            
            status.update(label="✅ Full Pipeline Complete", state="complete", expanded=False)
            time.sleep(0.5)
            
        st.rerun()
    except Exception as e:
        st.error(f"❌ Pipeline failed: {e}")

# --- DB HELPERS ---
def get_session():
    return SessionLocal()

def get_queue(session, filter_types=None):
    query = session.query(ProactiveOutreach).filter(
        ProactiveOutreach.status.in_(['queued', 'snoozed', 'sent']), # Include sent so we can see them unless filtered
        (ProactiveOutreach.next_action_at <= datetime.utcnow()) | (ProactiveOutreach.next_action_at == None),
        ProactiveOutreach.test_run_id == None
    )
    items = query.all()
    
    if filter_types:
        filtered = []
        for i in items:
            # Exclude sent if Hide Sent is checked, UNLESS it's the currently active one
            if 'Hide Sent' in filter_types and i.status == 'sent': 
                if st.session_state.get("active_outreach_id") != i.id:
                    continue
            
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
    # Increase refresh to 5 mins so it doesn't kill long-running LLM calls
    st_autorefresh(interval=300000, limit=None, key="cockpit_refresh")
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
        
        # Auto-recover latest export (persistence fix)
        if not st.session_state.get("export_path"):
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                candidates = [f for f in os.listdir(base_dir) if f.startswith(("codebase_summary_", "incremental_summary_")) and f.endswith(".md")]
                if candidates:
                    latest = max(candidates, key=lambda f: os.path.getmtime(os.path.join(base_dir, f)))
                    abs_path = os.path.join(base_dir, latest)
                    st.session_state["export_path"] = abs_path
                    st.session_state["export_filename"] = latest
                    
                    # Try to reconstruct SCP command
                    from create_export import generate_scp_command
                    cmd, _ = generate_scp_command(abs_path, windows_username="chris")
                    if cmd:
                        st.session_state["export_scp_command"] = cmd
                        st.session_state["export_scp_success"] = False # Status unknown
            except Exception: pass

        scp_cmd = st.session_state.get("export_scp_command")
        
        # Direct Download Button (New)
        if st.session_state.get("export_path") and os.path.exists(st.session_state.get("export_path")):
            try:
                with open(st.session_state["export_path"], "rb") as f:
                    st.download_button(
                        label="📥 Download Export (Browser)",
                        data=f,
                        file_name=st.session_state.get("export_filename", "codebase_summary.md"),
                        mime="text/markdown",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"Ready to download, but file not found: {e}")

        if scp_cmd:
            with st.expander("🔧 SCP command (Alternative)", expanded=not st.session_state.get("export_scp_success")):
                st.info("Run this in **Windows PowerShell** (not this terminal):")
                st.code(scp_cmd, language="powershell")

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
            
        st.markdown("### 📧 Mailgun Health")
        if st.button("🔥 Send Smoke Test"):
            with st.status("Sending test email...", expanded=True) as status:
                result = send_mailgun_test_email()
                if result.get("success"):
                    status.update(label="✅ Test email sent!", state="complete")
                    st.json(result["data"])
                    st.success("Check your inbox!")
                else:
                    status.update(label="❌ Test failed", state="error")
                    st.error(result.get("error"))

    tab_cockpit, tab_test = st.tabs(["🚀 Cockpit", "🧪 Test Scoring"])

    with tab_cockpit:
        col_queue, col_editor, col_insights = st.columns([1, 2, 1], gap="small")

        with col_queue:
            st.header("Inbox")
            
            # View Mode Toggle
            view_mode = st.radio("View:", ["Due Only", "All Pipeline", "All Companies"], horizontal=True, label_visibility="collapsed")
            
            filters = ['Job Applications', 'Signal Outreaches', 'Follow-ups']
            selected_filters = st.multiselect("Filters:", filters, default=filters)
            hide_sent = st.checkbox("Hide Sent", value=True)
            
            if hide_sent: selected_filters.append('Hide Sent')
            
            if view_mode == "Due Only":
                queue_items = get_queue(session, selected_filters)
                st.caption(f"{len(queue_items)} items due")
            elif view_mode == "All Pipeline":
                # Fetch recent active outreaches
                queue_items = session.query(ProactiveOutreach).filter(
                    ProactiveOutreach.status.notin_(['archived'])
                ).order_by(ProactiveOutreach.updated_at.desc()).limit(100).all()
                st.caption(f"{len(queue_items)} recent items")
            else: # All Companies (Registry Mode: Pipeline + Golden Leads)
                st.caption("Loading Registry (DB + Golden Leads)...")
                try:
                    # 1. Fetch Everything in Pipeline
                    db_items = session.query(ProactiveOutreach).filter(
                        ProactiveOutreach.status.notin_(['archived'])
                    ).all()
                    
                    # 2. Load Golden Leads
                    with open("config/golden_leads.yaml", "r") as f:
                        leads_data = yaml.safe_load(f)
                    
                    golden_names = set([g.get('company_name') for g in leads_data if g.get('company_name')])
                    
                    # 3. Identify Missing Golden Leads (Registry Items not yet in Pipeline)
                    # Create a set of normalized names currently in DB
                    db_company_names = set()
                    for i in db_items:
                        if i.company and i.company.name:
                            db_company_names.add(i.company.name)
                    
                    missing_names = [n for n in golden_names if n not in db_company_names]
                    
                    # 4. Create Ghost Items for Missing
                    from types import SimpleNamespace
                    ghost_items = []
                    for name in missing_names:
                        # logical_id to ensure uniqueness
                        ghost_id = f"ghost_{name.replace(' ', '_')}"
                        ghost_item = SimpleNamespace(
                            id=ghost_id,
                            company_id=ghost_id,
                            company=SimpleNamespace(name=name),
                            fit_score=0,
                            priority_score=0,
                            lead_type='registry_only',
                            outreach_type='not_started',
                            status='new',
                            job=None,
                            created_at=None,
                            updated_at=None
                        )
                        ghost_items.append(ghost_item)
                    
                    queue_items = db_items + ghost_items
                        
                    st.caption(f"Found {len(queue_items)} total companies ({len(ghost_items)} from registry only)")
                except Exception as e:
                    st.error(f"Failed to load registry: {e}")
                    queue_items = []
            
            if queue_items:
                # Deduplicate by Company
                grouped_items = {}
                for item in queue_items:
                    cid = item.company_id or item.company.name # Fallback to name if ID missing (rare)
                    if cid not in grouped_items: grouped_items[cid] = []
                    grouped_items[cid].append(item)
                
                options_list = []
                # We need a way to map the "Representative ID" back to the Group
                representative_map = {} 
                
                for cid, items in grouped_items.items():
                    # Pick best item (highest priority/score)
                    # FIX: If one of the items is the *pinned active outreach*, force it to be the representative
                    forced_id = st.session_state.get("active_outreach_id")
                    
                    # Sort default way first
                    sorted_items = sorted(items, key=lambda x: (x.priority_score or 0, x.fit_score or 0), reverse=True)
                    best_item = sorted_items[0]
                    
                    if forced_id:
                        found_pinned = next((i for i in items if i.id == forced_id), None)
                        if found_pinned:
                            best_item = found_pinned
                    
                    # IMPORTANT: If 'Hide Sent' is active, but the pinned item IS SENT, we must NOT filter it out
                    # The higher level filter (before grouping) might have removed it, so we need to address that earlier 
                    # OR we handle it here if we move filtering.
                    # Currently filtering happens inside 'get_queue'.
                    
                    representative_map[best_item.id] = items # Store full list
                    
                    # Aggregate stats
                    max_score = max([i.fit_score or 0 for i in items])
                    count = len(items)
                    
                    # Icon logic
                    types = set([i.lead_type for i in items])
                    icon = "💼" if 'job_posting' in types else "📡" if 'signal_only' in types else "❓"
                    
                    indicator = "🟢" if max_score >= 80 else "🟡" if max_score >= 60 else "⚪"
                    company_name = best_item.company.name if best_item.company else 'Unknown'
                    
                    label = f"{indicator} {max_score} {icon} {company_name}"
                    if count > 1:
                        label += f" ({count})"
                    
                    # Add Flags
                    # Check recency of ANY item
                    recent = False
                    for i in items:
                        posted_at = i.job.date_posted if i.job and i.job.date_posted else i.created_at
                        if posted_at:
                            hours = (datetime.utcnow() - posted_at).total_seconds() / 3600
                            if hours < 72: recent = True
                    if recent: label += " 🔥"

                    golden = session.query(GoldenLead).filter(GoldenLead.company_name.ilike(f"%{company_name}%")).first()
                    if golden:
                        exp = golden.expected_fit_tier
                        if (exp == 'high' and max_score < 60) or (exp == 'medium' and max_score < 40):
                            label += " 🚩"
                            
                    options_list.append((label, best_item.id))
                
                # Sort the main list by score/priority of best item
                # (Simple alphanumeric sort of label usually works if indicator is first, but cleaner to sort `options_list` if needed)
                # Let's rely on the natural order from get_queue which was already sorted, but grouped dict might scramble.
                # Re-sort options based on Score (extracted from label or map).
                # Actually, standardizing sort: High Score -> Low Score
                options_list.sort(key=lambda x: int(x[0].split()[1]) if x[0].split()[1].isdigit() else 0, reverse=True)

                options_dict = {label: item_id for label, item_id in options_list}
                selected_label = st.radio("Select Company:", options=list(options_dict.keys()), label_visibility="collapsed")
                
                # Context Selector
                representative_id = options_dict.get(selected_label)
                if representative_id:
                    items = representative_map.get(representative_id, [])
                    if len(items) > 1:
                        # SORT contexts: Score DESC, Updated DESC
                        items = sorted(items, key=lambda x: (x.fit_score or 0, x.updated_at or datetime.min), reverse=True)
                        
                        # Create context labels
                        ctx_options = {}
                        for i in items:
                            score = i.fit_score or 0
                            ago = ""
                            if i.updated_at:
                                hrs = (datetime.utcnow() - i.updated_at).total_seconds() / 3600
                                ago = f" • {hrs:.1f}h ago"
                                
                            i_label = f"{score}pts • {i.outreach_type}{ago}"
                            if i.job: i_label += f" - {i.job.title[:20]}..."
                            elif i.lead_type == 'signal_only': i_label += f" - {i.signal_summary[:30]}"
                            
                            ctx_options[i_label] = i.id
                        
                        ctx_label = st.selectbox("Select Context:", list(ctx_options.keys()), key="ctx_sel")
                        selected_id = ctx_options[ctx_label]
                    else:
                        selected_id = representative_id
                else:
                    selected_id = None
            else:
                selected_id = None

        if selected_id:
            outreach = session.query(ProactiveOutreach).get(selected_id)
            company = outreach.company
            contact = outreach.contact
            job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
            
            
            effective_email = contact.email if contact else ""
            effective_name = contact.name if contact else ""
            
            if contact and contact.apollo_id:
                cache_map = _load_enrichment_cache()
                cached = cache_map.get(contact.apollo_id)
                if cached:
                    # SAFETY GUARD: Check for ID mismatch (Stale ID pointing to wrong person)
                    # Use first name comparison
                    db_name_parts = (contact.name or "").lower().split()
                    cache_name_parts = (cached.get('first_name') or cached.get('name') or "").lower().split()
                    
                    is_match = True
                    if db_name_parts and cache_name_parts:
                        if db_name_parts[0] != cache_name_parts[0]:
                            is_match = False
                    
                    if is_match:
                        # Robust extraction from cache
                        e = cached.get('email')
                        if e and "email_not_unlocked" not in e:
                            effective_email = e
                        elif not effective_email: # Try personal if no db email
                             p_emails = cached.get('personal_emails', [])
                             if p_emails and isinstance(p_emails, list):
                                 effective_email = p_emails[0]
                    else:
                        # Mismatch detected - Ignore cache
                        pass
            
            # Persist to session for editor
            # CRITICAL FIX: Respect database authority first
            if outreach.contact_id and contact:
               st.session_state['recipient_email'] = effective_email # This is still computed correctly from contact/cache above
               st.session_state['recipient_name'] = contact.name # Use the canonical name from DB
            else:
               st.session_state['recipient_email'] = effective_email
               st.session_state['recipient_name'] = effective_name

            # --- Sidebar Context (Apollo) ---
            with st.sidebar:
                st.markdown("---")
                st.subheader("🕵️ Contact Finder")
                st.caption(f"Outreach ID: {outreach.id[:8]}")
                
                # --- CONTACT FINDER: AUTHORITATIVE RENDER LOGIC ---
                # Step 1: Load DB-authoritative contact
                assigned_contact = None
                if outreach.contact_id:
                    assigned_contact = (
                        session.query(Contact)
                        .filter(Contact.id == outreach.contact_id)
                        .first()
                    )
                
                # Step 2: Load inferred candidate (optional, secondary)
                # Only infer if no assigned contact exists
                candidate_contact = None
                if not assigned_contact:
                    # Try to infer from search results (first result if available)
                    found_contacts = st.session_state.get(f"contacts_{outreach.id}", [])
                    if found_contacts:
                        # Use first search result as candidate
                        c = found_contacts[0]
                        # Create a simple dict representation for candidate
                        candidate_contact = {
                            'name': c.get('name', 'Unknown'),
                            'title': c.get('title', ''),
                            'email': c.get('email'),
                            'email_verified': c.get('email_status') == 'verified' if c.get('email_status') else False,
                            'apollo_id': c.get('apollo_id'),
                            'linkedin_url': c.get('linkedin_url')
                        }
                
                # Step 3: Render Contact Finder (STRICT order)
                if assigned_contact:
                    st.markdown(f"**Assigned:** {assigned_contact.name}")
                    
                    # Compute enriched email for assigned contact (if needed)
                    assigned_email = assigned_contact.email
                    if not assigned_email and assigned_contact.apollo_id:
                        # Try to get from enrichment cache
                        cached = get_enriched_data(assigned_contact.apollo_id)
                        if cached:
                            e = cached.get('email')
                            if e and "email_not_unlocked" not in e:
                                assigned_email = e
                            elif not assigned_email:
                                p_emails = cached.get('personal_emails', [])
                                if p_emails and isinstance(p_emails, list):
                                    assigned_email = p_emails[0]
                    
                    # Check if email was sent
                    sent_primary = None
                    check_email = assigned_contact.email or assigned_email or effective_email
                    if check_email:
                        sent_primary = get_last_outbound_email(check_email, company.name)
                    
                    if outreach.status == "sent":
                        st.success("✉️ Email sent")
                    else:
                        st.info("📌 Assigned contact")
                    
                    # Email display with state-specific messages
                    display_email = assigned_contact.email or assigned_email
                    if display_email:
                        st.markdown(f"📧 {display_email}")
                        # Check if verified (from enrichment cache)
                        if assigned_contact.apollo_id:
                            cached = get_enriched_data(assigned_contact.apollo_id)
                            if cached and cached.get('email_status') == 'verified':
                                st.caption("✅ Verified email")
                            else:
                                st.caption("⚠️ Unverified email")
                        else:
                            st.caption("⚠️ Unverified email")
                    elif sent_primary:
                        # Email was sent but not in DB record
                        st.caption("📨 Email previously sent (address on file)")
                    else:
                        st.caption("ℹ️ No email on record (not searched or not found)")
                    
                    # Show sent email details if available
                    if sent_primary:
                        with st.expander("View Last Email", expanded=False):
                            st.caption(f"**Subject:** {sent_primary['subject']}")
                            st.caption(f"**Ref:** {sent_primary['mailgun_message_id']}")
                            st.text(sent_primary['body_text'])
                    
                    # OPTIONAL: Show candidate contact if both exist
                    if candidate_contact:
                        st.divider()
                        st.caption("Other possible contacts:")
                        st.markdown(f"- {candidate_contact['name']} (not assigned)")
                    
                    st.divider()
                    
                elif candidate_contact:
                    st.markdown(f"**Suggested:** {candidate_contact['name']}")
                    
                    if candidate_contact.get('email'):
                        st.markdown(f"📧 {candidate_contact['email']}")
                        st.caption("⚠️ Unverified email (candidate)")
                    else:
                        st.caption("❌ No email found for this candidate")
                    
                    st.divider()
                    
                else:
                    st.caption("No contact identified yet")
                    st.divider()
                
                st.caption(f"Target: {company.name}")
                
                default_role = "Head of Sales, VP Sales, Chief Revenue Officer"
                target_role = st.text_input("Role Keywords", value=default_role, help="Comma-separated titles")
                
                c_search1, c_search2, c_search3 = st.columns([1,1,1])
                with c_search1:
                    if st.button("Search Apollo", help="Search using specific keywords above", use_container_width=True):
                        st.session_state.pop(f"contacts_{outreach.id}", None)
                        with st.status("🔍 Searching Apollo...", expanded=True) as status:
                            try:
                                contacts, debug_info = find_contacts_for_lead(company.name, target_role, limit=3)
                                st.session_state[f"contacts_{outreach.id}"] = contacts
                                st.session_state[f"apollo_debug_{outreach.id}"] = debug_info
                                
                                if contacts:
                                    status.update(label=f"✅ Found {len(contacts)} contacts!", state="complete")
                                else:
                                    identifier = debug_info.get('resolved_domain') or f"OrgID {debug_info.get('resolved_org_id')}"
                                    status.update(label=f"❌ No contacts at {identifier}", state="error")
                            except Exception as e:
                                st.error(f"Error: {e}")
                
                with c_search2:
                    if st.button("Broad Search", help="Search 'Sales/Growth' at this Org ID (ignores custom roles)", use_container_width=True):
                         # Clear previous results to avoid confusion
                         st.session_state.pop(f"contacts_{outreach.id}", None)
                         
                         with st.status("🔍 Broad Org Search...", expanded=True) as status:
                            try:
                                # Use generic titles
                                broad_query = "Sales, Business Development, Growth, CEO, Founder"
                                contacts, debug_info = find_contacts_for_lead(company.name, broad_query, limit=5)
                                st.session_state[f"contacts_{outreach.id}"] = contacts
                                st.session_state[f"apollo_debug_{outreach.id}"] = debug_info
                                
                                if contacts:
                                    status.update(label=f"✅ Found {len(contacts)} contacts!", state="complete")
                                else:
                                    status.update(label="❌ No contacts found.", state="error")
                            except Exception as e:
                                st.error(str(e))
                
                with c_search3:
                    # FIX: Disable AI Research if we already have an assigned contact
                    ai_disabled = (outreach.contact_id is not None)
                    if st.button("AI Research", help="Ask Perplexity for Names + Strategy" + (" (Disabled: Contact Assigned)" if ai_disabled else ""), use_container_width=True, disabled=ai_disabled):
                         if ai_disabled:
                             st.warning("Contact already assigned. Unassign or manually edit to research others.")
                         else:
                             st.session_state.pop(f"contacts_{outreach.id}", None)
                             with st.status("🤖 AI Researching...", expanded=True) as status:
                                 try:
                                     # 1. Get Names from AI
                                     ai_contacts = find_contacts_via_perplexity(company.name, target_role)
                                     status.write(f"Found {len(ai_contacts)} potential leaders via AI...")
                                     
                                     # 2. Enrich via Apollo (if possible)
                                     apollo = ApolloClient()
                                     final_contacts = []
                                     
                                     # Try to resolve domain once for efficiency
                                     dom = None
                                     try:
                                         orgs = apollo.search_organizations(company.name)
                                         if orgs:
                                             dom = orgs[0].get('primary_domain') or orgs[0].get('domain')
                                     except:
                                         pass
                                     
                                     for c in ai_contacts:
                                         name = c['name']
                                         if not name: continue
                                         
                                         status.write(f"Enriching {name}...")
                                         matches = apollo.enrich_person_by_name(name, company_domain=dom, company_name=company.name)
                                         
                                         if matches:
                                             # Use the Apollo match (it has email!)
                                             best = matches[0]
                                             # Keep the reason/notes from AI if useful
                                             best['reason'] = c.get('reason')
                                             final_contacts.append(best)
                                         else:
                                             # Fallback to AI-only
                                             final_contacts.append(c)
                                     
                                     st.session_state[f"contacts_{outreach.id}"] = final_contacts
                                     st.session_state[f"apollo_debug_{outreach.id}"] = {"source": "Perplexity + Apollo Enrich"}
                                     
                                     if final_contacts:
                                         status.update(label=f"✅ Found {len(final_contacts)} leaders ({len([x for x in final_contacts if x.get('email')])} emails)!", state="complete")
                                     else:
                                         status.update(label="❌ No leaders found via AI.", state="error")
                                 except Exception as e:
                                     st.error(str(e))

                # --- ✍️ Manual Entry Fallback ---
                with st.expander("✍️ Manual Entry (LinkedIn/SalesNav)", expanded=False):
                    with st.form("manual_contact_form"):
                        m_name = st.text_input("Name")
                        m_title = st.text_input("Title")
                        m_email = st.text_input("Email (optional)")
                        m_linkedin = st.text_input("LinkedIn URL")
                        
                        if st.form_submit_button("Save & Assign"):
                            if not m_name:
                                st.error("Name is required")
                            else:
                                # Create/Update Contact
                                if not contact:
                                    contact = Contact(
                                        id=str(uuid.uuid4()), 
                                        company_id=company.id, 
                                        name=m_name, 
                                        title=m_title, 
                                        email=m_email,
                                        linkedin_url=m_linkedin,
                                        apollo_id="manual"
                                    )
                                    session.add(contact)
                                    outreach.contact_id = contact.id
                                else:
                                    contact.name = m_name
                                    contact.title = m_title
                                    contact.email = m_email
                                    contact.linkedin_url = m_linkedin
                                    contact.apollo_id = "manual"
                                
                                session.add(outreach)
                                session.add(contact)
                                session.commit()
                                st.success(f"✅ Assigned: {m_name}")
                                time.sleep(1)
                                st.rerun()

                # Display Results
                found_contacts = st.session_state.get(f"contacts_{outreach.id}", [])
                debug_info = st.session_state.get(f"apollo_debug_{outreach.id}", {})
                
                if found_contacts:
                    src = debug_info.get('resolved_org_name') or debug_info.get('source') or "Unknown"
                    st.caption(f"Source: {src}")
                    st.markdown(f"**Results ({len(found_contacts)}):**")
                    for c in found_contacts:
                        # Overlay Cached Enrichment
                        if c.get('apollo_id'):
                            cached = get_enriched_data(c['apollo_id'])
                            if cached:
                                # Promote key fields
                                nf = cached.get('first_name', '').strip()
                                nl = cached.get('last_name', '').strip()
                                if nf and nl: c['name'] = f"{nf} {nl}"
                                
                                if cached.get('email'): c['email'] = cached['email']
                                if cached.get('email_status'): c['email_status'] = cached['email_status']
                                if cached.get('linkedin_url'): c['linkedin_url'] = cached['linkedin_url']
                                c['raw_fetch'] = cached # restore full object/wrapper
                                c['enriched_from_cache'] = True # flag for UI
                                
                                # LOG ASSERTION
                                logger.info(f"[UI] Overlay Contact {c.get('apollo_id')}: cache_email={cached.get('email')} display_email={c.get('email')}")
                                
                        source_code = c.get('source')
                        if source_code == 'apollo_search':
                            source_label = "🔷 Apollo Search"
                        elif source_code == 'apollo_from_ai':
                            source_label = "✅ Apollo Verified"
                        elif source_code == 'perplexity_ai':
                            source_label = "🤖 AI Suggestion"
                        else:
                            source_label = "❓ Unknown Source"
                            
                        # DEBUG PROBES
                        # st.caption(f"DEBUG keys: {list(c.keys())}")
                        # st.caption(f"DEBUG raw items: {len(c.get('raw_data') or {})}")
                            
                        # Name Header
                        with st.expander(f"{source_label}: {c['name']}", expanded=True):
                            st.caption(f"DEBUG: keys={list(c.keys())} | raw_len={len(c.get('raw_data') or {})}")
                            st.caption(c['title'])
                            
                            # Email handling
                            email = c.get('email')

                            if email and "email_not_unlocked" in email:
                                st.write("🔒 `Verified (Gated by Apollo)`")
                                
                                # Reveal Button
                                if st.button("🔓 Reveal (1 Credit)", key=f"reveal_{c.get('apollo_id')}_{outreach.id}"):
                                    client = ApolloClient()
                                    
                                    revealed_wrapper = client.reveal_person_email(c['apollo_id'])
                                    revealed = revealed_wrapper.get('parsed_person')
                                    
                                    # ROBUST EXTRACTION
                                    real_email = None
                                    if revealed:
                                        # 1. Check primary email
                                        e = revealed.get('email')
                                        if e and "email_not_unlocked" not in e:
                                            real_email = e
                                        
                                        # 2. Fallback to personal emails
                                        if not real_email:
                                            p_emails = revealed.get('personal_emails', [])
                                            if p_emails and isinstance(p_emails, list):
                                                real_email = p_emails[0]
                                    
                                    if real_email:
                                        c['email'] = real_email
                                        c['email_status'] = revealed.get('email_status', 'verified')
                                        
                                        # Save to cache with the revealed data!
                                        save_enrichment_cache(c['apollo_id'], revealed)
                                        
                                        credits = revealed_wrapper.get('credits_consumed', '?')
                                        st.success(f"Revealed: {real_email} (Credits: {credits})")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        c['raw_reveal'] = revealed_wrapper
                                        st.error(f"Reveal failed or no email found. (Credits: {revealed_wrapper.get('credits_consumed', 0)})")

                            
                            elif email and "No email" not in email:
                                st.write(f"📧 `{email}`")
                            else:
                                status_text = c.get('email_status')
                                if status_text == 'unavailable':
                                    st.caption(f"🚫 Email Unavailable")
                                elif status_text:
                                    st.caption(f"🔒 Email Status: {status_text}")
                                else:
                                    st.caption("❓ Email Status: Unknown (Fetch to check)")
                                    
                                # Fetch/Unlock Button
                                if c.get('apollo_id'):
                                    if st.button("🔄 Fetch Details (1 Credit)", key=f"unlock_{c.get('apollo_id')}_{outreach.id}"):
                                        client = ApolloClient()
                                        
                                        # Get wrapper
                                        enriched_wrapper = client.unlock_person_email(c['apollo_id'])
                                        
                                        # Update raw_fetch with full diagnosis
                                        c['raw_fetch'] = enriched_wrapper
                                        
                                        # Extract actual person data if present
                                        enriched = enriched_wrapper.get('parsed_person')
                                        
                                        if enriched:
                                            # SAVE TO CACHE
                                            save_enrichment_cache(c['apollo_id'], enriched)
                                            
                                            changes = []
                                            
                                            # Email Diff
                                            new_email = enriched.get('email')
                                            if new_email and new_email != c.get('email'):
                                                c['email'] = new_email
                                                changes.append("email")
                                            
                                            # Status Diff
                                            new_status = enriched.get('email_status') or 'fetched'
                                            if new_status != c.get('email_status'):
                                                c['email_status'] = new_status
                                                changes.append("status")
                                                
                                            # LinkedIn Diff
                                            new_linked = enriched.get('linkedin_url')
                                            if new_linked and new_linked != c.get('linkedin_url'):
                                                c['linkedin_url'] = new_linked
                                                changes.append("linkedin")
                                            
                                            # Name Diff
                                            nf = enriched.get('first_name', '').strip()
                                            nl = enriched.get('last_name', '').strip()
                                            new_name = f"{nf} {nl}".strip()
                                            if new_name and new_name != c.get('name'):
                                                c['name'] = new_name
                                                changes.append("name")
                                            
                                            # Persist state explicitly
                                            st.session_state[f"contacts_{outreach.id}"] = found_contacts
                                            
                                            if changes:
                                                st.success(f"✅ Fetched: {', '.join(changes)}")
                                            else:
                                                st.info("ℹ️ Fetched details, but no new data found.")
                                        else:
                                            # Persist result state even if empty/error
                                            st.session_state[f"contacts_{outreach.id}"] = found_contacts
                                            status_code = enriched_wrapper.get('http_status')
                                            if status_code == 200:
                                                st.warning("Request successful (200), but no person data returned.")
                                            else:
                                                st.error(f"Fetch failed: HTTP {status_code}")
                                        
                                        time.sleep(1)
                                        st.rerun()
                                
                                if st.button("🔍 Enrich via Lux", key=f"lux_{c['name']}_{outreach.id}", help="Generate prompt for Lux"):
                                    prompt = f"""**Task for Lux:** Find verified email via Sales Nav + Snov.io for:
- Name: {c['name']}
- Title: {c['title']}
- Company: {company.name}"""
                                    st.code(prompt, language="markdown")
                            
                            # Debug Data (Unconditional)
                            with st.expander("🔍 Debug Data"):
                                st.markdown("**Original Search (raw_data):**")
                                st.json(c.get('raw_data') or {})
                                
                                st.markdown("**Fetched Enrichment (raw_fetch):**")
                                st.json(c.get('raw_fetch') or {"status": "Not fetched yet"})
                                
                            # Use Button
                            if st.button("Use this Contact", key=f"use_{c['name']}_{outreach.id}", use_container_width=True):
                                # Update database contact
                                contact = Contact(id=str(uuid.uuid4()), company_id=company.id)
                                session.add(contact)
                                outreach.contact_id = contact.id
                                
                                # Always update all fields
                                contact.name = c['name']
                                contact.title = c['title']
                                contact.email = email
                                contact.linkedin_url = c.get('linkedin_url')
                                contact.apollo_id = c.get('apollo_id')
                                contact.confidence_score = 100 # Manual selection implies 100% confidence
                                
                                # --- Auto-Patch Draft Salutation ---
                                # If a draft exists, update the greeting to match the new contact
                                def _patch_salutation(text, new_name):
                                    if not text: return text
                                    lines = text.split('\n')
                                    if not lines: return text
                                    # Match "Dear Name," or "Hi Name,"
                                    # Group 1: Greeting word, Group 2: Old Name, Group 3: Punctuation
                                    match = re.match(r'^(Dear|Hi|Hello)\s+(.+?)(,|:|$)', lines[0].strip(), re.IGNORECASE)
                                    if match:
                                        greeting = match.group(1)
                                        punct = match.group(3) or ","
                                        # Preserve original spacing/indent if any (though strip() removed it above, usually safe to standardise)
                                        lines[0] = f"{greeting} {new_name}{punct}"
                                        return "\n".join(lines)
                                    return text

                                if outreach.px_final_email:
                                    outreach.px_final_email = _patch_salutation(outreach.px_final_email, c['name'])
                                if outreach.draft_email:
                                    outreach.draft_email = _patch_salutation(outreach.draft_email, c['name'])
                                if outreach.ds_raw_draft:
                                    outreach.ds_raw_draft = _patch_salutation(outreach.ds_raw_draft, c['name'])
                                # -----------------------------------

                                session.add(outreach)
                                session.commit()
                                
                                # Clear session state overrides immediately
                                st.session_state.pop('recipient_email', None)
                                st.session_state.pop('recipient_name', None)
                                st.session_state.pop('manual_email_edit', None)
                                
                                # Clear draft body override to prevent stale greetings
                                st.session_state.pop(f"draft_text_{outreach.id}", None)
                                
                                st.success(f"✅ Assigned: {c['name']}!")
                                time.sleep(0.5)
                                st.rerun()
                            
                            if c.get('reason'):
                                st.info(c['reason'])
                elif f"contacts_{outreach.id}" in st.session_state and not found_contacts:
                    st.caption(f"No matches via Key: {debug_info.get('active_key_masked')}")
                    if debug_info.get('error'):
                         st.error(debug_info['error'])

            with col_editor:
                st.subheader(f"{company.name}")
                
                # --- Editor State Management ---
                # (Logic moved to Draft Email section below)
                
                # 1. Strategy Context (Moved to Top & Expanded)
                with st.expander("🎯 Strategy & Fit", expanded=True):
                    # Job traceability in header
                    st.write(f"Company: **{company.name}** ({company.vertical})")
                    
                    # FALLBACK LOGIC: Check outreach first, then linked job
                    display_title = outreach.role_title or (outreach.job.title if outreach.job else "Unknown Role")
                    display_url = outreach.job_url or (outreach.job.url if outreach.job else None)
                    display_source = outreach.job_source or (outreach.job.source if outreach.job else "unknown")
                    
                    job_link = f"[{display_title}]({display_url})" if display_url else display_title
                    st.markdown(f"Job: {job_link}")
                    
                    age_h = None
                    posted_ts = None
                    ts_type = "Unknown"
                    
                    if outreach.job:
                        if outreach.job.date_posted:
                            posted_ts = outreach.job.date_posted
                            ts_type = "Posted"
                        elif outreach.job.created_at:
                            posted_ts = outreach.job.created_at
                            ts_type = "First Seen"
                    
                    if posted_ts:
                        age_h = (datetime.utcnow() - posted_ts).total_seconds() / 3600
                        age_label = f"{age_h:.1f}h"
                    else:
                        age_label = "N/A"
                    
                    st.caption(f"Source: {display_source} • {ts_type} {age_label} ago")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("Fit Score", value=outreach.fit_score)
                    c2.metric("Recency", value=age_label)
                    
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
                        
                        if job:
                             if job.date_posted:
                                 cols[1].write(f"Posted: {job.date_posted}")
                             elif job.created_at:
                                 cols[1].write(f"First Seen: {job.created_at}")
                             else:
                                 cols[1].write("Timestamps: None")
                        
                        cols[1].write(f"Recency Score: {bd['recency_score']}")
                            
                        cols[1].write(f"Signal: {bd['signal_score']}")
                        cols[1].write(f"Role Adj: {bd['role_adjustment']}")
                        st.divider()
                        st.write(f"**Total: {bd['final_score']}**")
                    
                    if outreach.fit_explanation: st.markdown(f"**Angle:** {outreach.fit_explanation}")
                
                # 2. Job Context Context (New)
                # Fallbacks for context block
                ctx_url = outreach.job_url or (outreach.job.url if outreach.job else None)
                ctx_title = outreach.role_title or (outreach.job.title if outreach.job else "Link")
                ctx_snippet = outreach.job_snippet or (outreach.job.description[:300] if outreach.job and outreach.job.description else None)
                ctx_location = outreach.job_location or (outreach.job.location if outreach.job else None)

                with st.expander("📄 Job Context", expanded=True):
                    if ctx_url:
                        st.markdown(f"**Job:** [{ctx_title}]({ctx_url})")
                    if ctx_location:
                        st.write(f"**Location:** {ctx_location}")
                    if ctx_snippet:
                        st.write(f"**Snippet:** {ctx_snippet}...")

                # 3. Email Draft Space
                st.subheader("Draft Email")
                
                draft_key = f"draft_text_{outreach.id}"

                # Initialize from DB on every rerun if not present
                # OR check for stale greeting in existing session state
                
                # 1. Determine the authoritative draft text (from DB)
                raw_text = (
                    outreach.px_final_email
                    or outreach.draft_email 
                    or ""
                )
                
                
                # 2. Patch greeting if we have a contact (Fixes persistence mismatch on refresh)
                if contact and contact.name:
                    def _patch_salutation_load(text, new_name):
                        if not text: return text
                        lines = text.split('\n')
                        if not lines: return text
                        
                        # Iterate to find the greeting line (it might be after Subject:)
                        for i, line in enumerate(lines):
                            # Skip empty lines or Subject lines
                            if not line.strip() or line.strip().lower().startswith("subject:"):
                                continue
                                
                            # Match "Dear Name," or "Hi Name,"
                            match = re.match(r'^\s*(Dear|Hi|Hello)\s+(.+?)(,|:|$)', line, re.IGNORECASE)
                            if match:
                                # Only patch if name is different
                                old_name = match.group(2).strip()
                                # Use loose comparison to allow for manual minor edits
                                if old_name.lower() != new_name.lower():
                                    greeting = match.group(1)
                                    punct = match.group(3) or ","
                                    lines[i] = f"{greeting} {new_name}{punct}"
                                    return "\n".join(lines)
                                # If we found a greeting but names match, stop scanning
                                return text
                                
                        return text
                        
                    raw_text = _patch_salutation_load(raw_text, contact.name)
                
                # 3. Aggressive State Management
                # If key missing -> Set it
                if draft_key not in st.session_state:
                    st.session_state[draft_key] = sanitize_email_text(raw_text)
                else:
                    # If key exists, check if it's holding a stale greeting (Seth) vs current contact (Stephen)
                    current_val = st.session_state[draft_key]
                    if contact and contact.name:
                         # Re-run patch check on the *session* value
                        normalized_val = _patch_salutation_load(current_val, contact.name)
                        if normalized_val != current_val:
                            # We found a stale greeting in session state -> Force update it
                            st.session_state[draft_key] = normalized_val
                            
                draft_text = st.text_area(
                    "Draft Editor",
                    key=draft_key,
                    height=300,
                    label_visibility="collapsed"
                )
                
                # --- Subject & Body Extraction ---
                current_subject = outreach.role_title or f"Partnership with {company.name}"
                current_body = draft_text
                
                if "Subject:" in draft_text[:100]:
                    lines = draft_text.split('\n')
                    subject_line = next((l for l in lines if l.startswith("Subject:")), None)
                    if subject_line:
                        current_subject = subject_line.replace("Subject:", "").strip()
                        current_body = "\n".join([l for l in lines if l != subject_line]).strip()

                # --- Safety Validation ---
                is_safe_body, reasons_body = validate_send_safe(current_body)
                is_safe_subj, reasons_subj = validate_send_safe(current_subject)
                is_safe = is_safe_body and is_safe_subj
                
                if is_safe:
                    st.caption(f"✅ Send-safe (Subject: '{current_subject[:40]}...')")
                else:
                    all_reasons = []
                    if not is_safe_body: all_reasons.append(f"Body: {reasons_body}")
                    if not is_safe_subj: all_reasons.append(f"Subject: {reasons_subj}")
                    
                    st.error(f"❌ Safety Check Failed: {'; '.join(all_reasons)}")
                    if st.button("🧹 Auto-Clean Artifacts", key=f"clean_{outreach.id}"):
                        st.session_state[draft_key] = sanitize_email_text(draft_text)
                        st.rerun()
                
                # --- Send Logic ---
                st.markdown("### 🚀 Launch")
                c_send1, c_send2 = st.columns([2, 1])
                with c_send1:
                    sender_options = list(SENDER_ADDRESSES.keys())
                    sender_key_ui = st.selectbox("Send from identity", options=sender_options, format_func=lambda x: f"{x.title()} ({SENDER_ADDRESSES[x]})")
                
                with c_send2:
                    # Target Email Input
                    # Use hydrated session state if available, else DB fallback
                    hydrated_email = st.session_state.get('recipient_email', contact.email if contact and contact.email else "")
                    
                    edit_recipient = st.checkbox("Edit", value=False)
                    
                    c_email, c_lux = st.columns([3, 1])
                    with c_email:
                        if edit_recipient:
                            target_email_ui = st.text_input("Target Email", value=hydrated_email, key="manual_email_edit", label_visibility="collapsed")
                        else:
                            if hydrated_email:
                                st.info(f"📤 To: **{hydrated_email}**")
                                target_email_ui = hydrated_email
                            else:
                                st.error("No recipient.")
                                target_email_ui = ""
                    with c_lux:
                        # Auto-show prompt logic or manual button
                        pass # handled below
                    
                    if not target_email_ui and contact and contact.name:
                        st.warning(f"⚠️ No email for {contact.name}. Ask Lux:")
                        prompt = f"""**Task for Lux:** Find verified email via Sales Nav + Snov.io for:
- Name: {contact.name}
- Title: {contact.title}
- Company: {company.name}"""
                        st.code(prompt, language="markdown")
                    elif st.button("🔍 Lux Check", help="Generate enrichment prompt"):
                         prompt = f"""**Task for Lux:** Find verified email via Sales Nav + Snov.io for:
- Name: {contact.name if contact else 'Unknown'}
- Title: {contact.title if contact else 'Sales Leader'}
- Company: {company.name}"""
                         st.code(prompt, language="markdown")
                    
                    st.write("") 
                    
                    # Pre-calculate subject for preview/edit logic
                    default_subject = current_subject
                    draft_content = current_body
                    
                    # --- Duplicate Send Guard ---
                    start_send = True
                    conf_override = False
                    
                    last_email_guard = get_last_outbound_email(target_email_ui, company.name)
                    if last_email_guard:
                        delta = datetime.utcnow() - last_email_guard['created_at']
                        if delta.days < 7:
                            start_send = False
                            st.warning(f"⚠️ Already emailed {delta.days} days ago ({last_email_guard['created_at'].strftime('%b %d')}).")
                            conf_override = st.checkbox("I intend to resend anyway", value=False)
                    # ----------------------------

                    if st.button("✅ Approve & Send", type="primary", use_container_width=True, disabled=(not start_send and not conf_override)):
                        # Validation
                        if not target_email_ui or "@" not in target_email_ui:
                            st.error("❌ Invalid target email!")
                        elif not draft_text or len(draft_text) < 10:
                            st.error("❌ Draft is too short/empty.")
                        elif not is_safe:
                            st.error(f"❌ Cannot send unsafe draft. Please resolve safety issues displayed above.")
                        else:
                            with st.status("📧 Sending via Mailgun...", expanded=True) as status:
                                try:
                                    # Use the pre-calculated subject from above logic
                                    # Ideally we'd let user edit this in a UI field, but for now specific extraction is safer than hidden magic
                                    # Re-calculating to be safe inside the button scope
                                    final_subject = sanitize_email_text(default_subject)
                                    final_body = draft_content
                                    
                                    final_target_email = target_email_ui
                                    
                                    # Prepare Headers
                                    custom_headers = {
                                        "X-Outreach-Id": outreach.id,
                                        "X-Audit-For": final_target_email
                                    }
                                    
                                    status.write(f"**Subject:** {final_subject}")
                                    status.write(f"**To:** {final_target_email}")
                                    
                                    resp = send_email_via_mailgun(
                                        to_email=final_target_email,
                                        subject=final_subject,
                                        body=final_body,
                                        sender_key=sender_key_ui,
                                        extra_headers=custom_headers
                                    )
                                    
                                    if resp.get("success"):
                                        outreach.status = 'sent'
                                        outreach.sent_at = datetime.utcnow()
                                        outreach.sent_from_address = SENDER_ADDRESSES[sender_key_ui]
                                        outreach.mailgun_message_id = resp.get("message_id")
                                        
                                        # Log outbound emails per recipient (Primary + Audit)
                                        sent_list = resp.get("sent_to", [final_target_email])
                                        
                                        for recipient in sent_list:
                                            # Determine type
                                            e_type = 'primary' if recipient == final_target_email else 'audit'
                                            
                                            outbound_log = OutboundEmail(
                                                id=str(uuid.uuid4()),
                                                outreach_id=outreach.id,
                                                recipient_email=recipient,
                                                sender_email=SENDER_ADDRESSES[sender_key_ui],
                                                email_type=e_type,
                                                subject=final_subject,
                                                body_text=final_body,
                                                mailgun_message_id=resp.get("message_id")
                                            )
                                            session.add(outbound_log)
                                        
                                        session.add(outreach)
                                        session.commit()
                                        session.refresh(outreach)
                                        
                                        status.update(label="✅ Sent successfully!", state="complete")
                                        st.success(f"Email sent to {final_target_email}!")
                                        
                                        # --- LOCK SELECTION (Fix Context Switching) ---
                                        # Pin the current outreach ID so the UI doesn't jump to the next item in the group
                                        # This prevents the "Stephen sent -> Seth appears" confusion
                                        st.session_state["active_outreach_id"] = outreach.id
                                        # -----------------------------------------------
                                        
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        status.update(label="❌ Send failed", state="error")
                                        st.error(f"Mailgun error: {resp.get('error')}")
                                
                                except Exception as e:
                                    status.update(label="❌ Send failed", state="error")
                                    st.error(f"Error: {str(e)}")

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
                
                # --- Action Status Placeholder (Ensures visibility) ---
                action_status = st.empty()
                
                st.markdown("### ⚡ V2 Pipeline")
                btn1, btn2 = st.columns(2)
                with btn1:
                    # DeepSeek is now optional / enhancer
                    if st.button("🧠 Stage 1: DeepSeek (Optional)", key="btn_ds_v2", use_container_width=True): 
                        run_deepseek_stage(outreach, company, contact, job, session, action_status)
                with btn2:
                    # Perplexity is always available
                    if st.button("🌐 Stage 2: Perplexity (Draft)", key="btn_px_v2", type="primary", use_container_width=True): 
                        run_perplexity_stage(outreach, company, contact, job, session, action_status)
                
                if st.button("🚀 Run Full Pipeline (Auto)", key="btn_full_v2", use_container_width=True): 
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

```
