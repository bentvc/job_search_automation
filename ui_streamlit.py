import streamlit as st
from streamlit_autorefresh import st_autorefresh
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job, GoldenLead, CandidateGoldenLead, CompanySignal
from datetime import datetime, timedelta
import urllib.parse
import uuid
from mailgun_client import send_email_via_mailgun, choose_sender_address, SENDER_ADDRESSES, send_mailgun_test_email
from apollo_client import find_contacts_for_lead
from llm_contact_finder import find_contacts_via_perplexity
from export_utility import get_last_export_timestamp
from create_export import run_export_and_transfer
import os
import time
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
            # Exclude sent if Hide Sent is checked (passed as special string in types or separate arg? 
            # Let's assume filter_types contains 'Hide Sent' if checked)
            if 'Hide Sent' in filter_types and i.status == 'sent': continue
            
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
            filters = ['Job Applications', 'Signal Outreaches', 'Follow-ups']
            selected_filters = st.multiselect("Filters:", filters, default=filters)
            hide_sent = st.checkbox("Hide Sent", value=True)
            
            if hide_sent: selected_filters.append('Hide Sent')
            
            queue_items = get_queue(session, selected_filters)
            st.caption(f"{len(queue_items)} items due")
            
            if queue_items:
                options_list = []
                for item in queue_items:
                    score = item.fit_score or 0
                    if item.status == 'sent':
                        indicator = "✅"
                    else:
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

            # --- Sidebar Context (Apollo) ---
            with st.sidebar:
                st.markdown("---")
                st.subheader("🕵️ Contact Finder")
                
                # Show current assignment
                if contact:
                    st.info(f"**Assigned:** {contact.name}\n\n`{contact.email}`")
                else:
                    st.warning("No contact assigned")
                
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
                    if st.button("AI Research", help="Ask Perplexity for Names + Strategy", use_container_width=True):
                         st.session_state.pop(f"contacts_{outreach.id}", None)
                         with st.status("🤖 AI Researching...", expanded=True) as status:
                            try:
                                # 1. Get Names from AI
                                ai_contacts = find_contacts_via_perplexity(company.name, target_role)
                                status.write(f"Found {len(ai_contacts)} potential leaders via AI...")
                                
                                # 2. Enrich via Apollo (if possible)
                                from apollo_client import ApolloClient
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
                            from apollo_client import get_enriched_data
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
                                st.caption("Use Lux/SalesNav to reveal.")
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
                                        from apollo_client import ApolloClient
                                        client = ApolloClient()
                                        
                                        # Get wrapper
                                        enriched_wrapper = client.unlock_person_email(c['apollo_id'])
                                        
                                        # Update raw_fetch with full diagnosis
                                        c['raw_fetch'] = enriched_wrapper
                                        
                                        # Extract actual person data if present
                                        enriched = enriched_wrapper.get('parsed_person')
                                        
                                        if enriched:
                                            # SAVE TO CACHE
                                            from apollo_client import save_enrichment_cache
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
                                if not contact:
                                    contact = Contact(id=str(uuid.uuid4()), company_id=company.id, name=c['name'], title=c['title'], email=email)
                                    session.add(contact)
                                    outreach.contact_id = contact.id
                                else:
                                    contact.name = c['name']
                                    contact.title = c['title']
                                    contact.email = email
                                
                                session.add(outreach)
                                session.commit()
                                st.success(f"✅ Assigned: {c['name']}!")
                                time.sleep(1)
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
                if draft_key not in st.session_state:
                    # Only Perplexity controls the final email now
                    st.session_state[draft_key] = (
                        outreach.px_final_email
                        or outreach.draft_email 
                        or ""
                    )

                draft_text = st.text_area(
                    "Draft Editor",
                    key=draft_key,
                    height=300,
                    label_visibility="collapsed"
                )
                
                # --- Send Logic ---
                st.markdown("### 🚀 Launch")
                c_send1, c_send2 = st.columns([2, 1])
                with c_send1:
                    sender_options = list(SENDER_ADDRESSES.keys())
                    sender_key_ui = st.selectbox("Send from identity", options=sender_options, format_func=lambda x: f"{x.title()} ({SENDER_ADDRESSES[x]})")
                
                with c_send2:
                    # Target Email Input
                    default_email = contact.email if contact and contact.email else ""
                    c_email, c_lux = st.columns([3, 1])
                    with c_email:
                        target_email_ui = st.text_input("Target Email", value=default_email, placeholder="[email protected]", label_visibility="collapsed")
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
                    default_subject = outreach.role_title or f"Partnership with {company.name}"
                    draft_content = draft_text
                    
                    if "Subject:" in draft_text[:100]:
                        lines = draft_text.split('\n')
                        subject_line = next((l for l in lines if l.startswith("Subject:")), None)
                        if subject_line:
                            default_subject = subject_line.replace("Subject:", "").strip()
                            draft_content = "\n".join([l for l in lines if l != subject_line]).strip()

                    if st.button("✅ Approve & Send", type="primary", use_container_width=True):
                        # Validation
                        if not target_email_ui or "@" not in target_email_ui:
                            st.error("❌ Invalid target email!")
                        elif not draft_text or len(draft_text) < 10:
                            st.error("❌ Draft is too short/empty.")
                        else:
                            with st.status("📧 Sending via Mailgun...", expanded=True) as status:
                                try:
                                    # Use the pre-calculated subject from above logic
                                    # Ideally we'd let user edit this in a UI field, but for now specific extraction is safer than hidden magic
                                    # Re-calculating to be safe inside the button scope
                                    final_subject = default_subject
                                    final_body = draft_content
                                    
                                    final_target_email = target_email_ui
                                    
                                    status.write(f"**Subject:** {final_subject}")
                                    status.write(f"**To:** {final_target_email}")
                                    
                                    resp = send_email_via_mailgun(
                                        to_email=final_target_email,
                                        subject=final_subject,
                                        body=final_body,
                                        sender_key=sender_key_ui
                                    )
                                    
                                    if resp.get("success"):
                                        outreach.status = 'sent'
                                        outreach.sent_at = datetime.utcnow()
                                        outreach.sent_from_address = SENDER_ADDRESSES[sender_key_ui]
                                        outreach.mailgun_message_id = resp.get("message_id")
                                        
                                        session.add(outreach)
                                        session.commit()
                                        session.refresh(outreach)
                                        
                                        status.update(label="✅ Sent successfully!", state="complete")
                                        st.success(f"Email sent to {final_target_email}!")
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
