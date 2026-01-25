import streamlit as st
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact, Job
from datetime import datetime, timedelta
import urllib.parse
import uuid
from mailgun_client import send_email_via_mailgun, choose_sender_address
from export_utility import get_last_export_timestamp
from create_export import run_export_and_transfer
import os
from pipeline_v2 import deepseek_analyze_and_draft, perplexity_finalize, run_v2_pipeline
import config

st.set_page_config(layout="wide", page_title="Job Search Cockpit")

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
    
    /* THICK VERTICAL DIVIDERS WITH INDEPENDENT SCROLLING */
    div[data-testid="column"] {
        border-right: 4px solid #d0d0d0;
        padding-right: 20px;
        padding-left: 10px;
        height: calc(100vh - 2rem);
        max-height: calc(100vh - 2rem);
        overflow-y: auto;
        overflow-x: hidden;
        position: relative;
    }
    div[data-testid="column"]:last-child {
        border-right: none;
    }
    
    /* Ensure columns scroll independently and maintain height */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        max-width: 100%;
    }
    
    /* Fix column height to viewport - target the horizontal block containing columns */
    section[data-testid="stMain"] > div:first-child > div:first-child {
        height: calc(100vh - 2rem);
    }
    
    /* Ensure each column container has proper height */
    div[data-testid="stHorizontalBlock"] > div {
        height: 100%;
    }
    
    /* Sidebar styling - make it collapsible-friendly */
    [data-testid="stSidebar"] {
        transition: transform 0.3s ease;
    }
    
    /* Ensure sidebar content scrolls if needed */
    [data-testid="stSidebar"] > div:first-child {
        height: 100vh;
        overflow-y: auto;
    }
    
    .queue-item {
        padding: 12px;
        border-bottom: 1px solid #ddd;
        cursor: pointer;
        margin-bottom: 4px;
        border-radius: 4px;
    }
    .queue-item:hover {
        background-color: #f0f2f6;
    }
    /* Distinctive colors for buttons */
    .sent-btn button { background-color: #4CAF50 !important; color: white !important; }
    .replied-btn button { background-color: #2196F3 !important; color: white !important; }
    .dismiss-btn button { background-color: #f44336 !important; color: white !important; }
    
    /* Smooth scrolling */
    div[data-testid="column"] {
        scroll-behavior: smooth;
    }
</style>
""", unsafe_allow_html=True)

# --- DB HELPERS ---
def get_session():
    return SessionLocal()

def get_queue(session, filter_types=None):
    query = session.query(ProactiveOutreach).filter(
        ProactiveOutreach.status.in_(['queued', 'snoozed']),
        (ProactiveOutreach.next_action_at <= datetime.utcnow()) | (ProactiveOutreach.next_action_at == None)
    )
    
    # Filter by Type in SQL where possible to reduce load
    # ... (skipping complex SQL for now)

    items = query.all()
    
    # Python-side filtering for flexibility
    if filter_types:
        filtered = []
        for i in items:
            if 'Job Applications' in filter_types and 'job' in i.outreach_type: filtered.append(i)
            elif 'Signal Outreaches' in filter_types and 'signal' in i.outreach_type: filtered.append(i)
            elif 'Follow-ups' in filter_types and 'followup' in i.outreach_type: filtered.append(i)
        items = filtered
    
    # Custom Sort: Primary by Score (desc), Secondary by Type Priority
    def sort_key(x):
        type_priority = 0 if x.lead_type == 'job_posting' else 1 if x.lead_type == 'signal_only' else 2
        score = x.fit_score if x.fit_score is not None else 0
        return (-score, type_priority)
        
    return sorted(items, key=sort_key)

# --- MAILTO BUILDER ---
def build_mailto(outreach, contact):
    if not contact or not contact.email: return None
    
    subject = f"Connecting - {contact.name}"
    # If job based, maybe "Role: {job_title}"
    if outreach.job_id:  # naive check, we'd need job object
        subject = f"Regarding {outreach.company.name} role"
        
    body = outreach.draft_email or ""
    
    params = {
        "to": contact.email,
        "subject": subject,
        "body": body
    }
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"mailto:{qs}"

# --- V2 PIPELINE HANDLERS ---
def run_deepseek_stage(outreach, company, contact, job, session):
    try:
        company_name = company.name if company else "Unknown"
        role = job.title if job else (contact.title if contact else "Executive Role")
        job_description = job.description if job else (outreach.signal_summary or "")
        sender_profile = config.USER_PROFILE_SUMMARY

        with st.spinner("🧠 DeepSeek analyzing (local, free)..."):
            result = deepseek_analyze_and_draft(
                company=company_name,
                role=role,
                job_description=job_description,
                sender_profile=sender_profile,
                use_local=True,
                company_vertical=company.vertical if company else None
            )

        outreach.ds_wedge = result.get("wedge")
        outreach.ds_rationale = "\n".join(result.get("rationale_bullets", []))
        outreach.ds_key_points = result.get("proof_points", [])
        outreach.ds_raw_draft = result.get("email_draft", "")

        session.commit()
        st.success("✅ DeepSeek Stage 1 complete! Check the DeepSeek Strategy section.")
        st.rerun()
    except ValueError as ve:
        st.warning(f"⚠️ DeepSeek output looked invalid: {ve}. Please try again or adjust the prompt.")
        # No rerun or commit needed for validation failure
    except Exception as e:
        st.error(f"❌ DeepSeek failed: {e}")
        st.exception(e)


def run_perplexity_stage(outreach, company, contact, job, session):
    ds_wedge = getattr(outreach, "ds_wedge", None)
    ds_rationale = getattr(outreach, "ds_rationale", None)
    ds_key_points = getattr(outreach, "ds_key_points", None)
    ds_raw_draft = getattr(outreach, "ds_raw_draft", None)

    if not ds_wedge or not ds_rationale or not ds_key_points or not ds_raw_draft:
        st.warning("⚠️ Run DeepSeek Stage 1 first! Missing required DeepSeek data.")
        return

    try:
        company_name = company.name if company else "Unknown"
        role = job.title if job else (contact.title if contact else "Executive Role")
        job_description = job.description if job else (outreach.signal_summary or "")
        job_url = job.url if job else None
        sender_profile = config.USER_PROFILE_SUMMARY

        with st.spinner("🌐 Perplexity verifying & finalizing (web search, ~1¢)..."):
            result = perplexity_finalize(
                company=company_name,
                role=role,
                job_description=job_description,
                job_url=job_url,
                sender_profile=sender_profile,
                ds_wedge=ds_wedge,
                ds_rationale=ds_rationale,
                ds_proof_points=ds_key_points if isinstance(ds_key_points, list) else [],
                ds_raw_draft=ds_raw_draft,
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )

        new_email = result.get("final_email")
        if new_email:
            outreach.px_final_email = new_email
            
        outreach.px_confidence = result.get("confidence")
        outreach.px_factual_flags = result.get("factual_flags", [])
        outreach.px_citations = result.get("citations", [])

        session.commit()
        st.success("✅ Perplexity Stage 2 complete! Check the Perplexity Final Email section.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Perplexity failed: {e}")
        st.exception(e)


def run_full_v2_pipeline(outreach, company, contact, job, session):
    try:
        company_name = company.name if company else "Unknown"
        role = job.title if job else (contact.title if contact else "Executive Role")
        job_description = job.description if job else (outreach.signal_summary or "")
        job_url = job.url if job else None
        sender_profile = config.USER_PROFILE_SUMMARY

        with st.spinner("🚀 Running Full V2 Pipeline (DeepSeek → Perplexity)..."):
            result = run_v2_pipeline(
                company=company_name,
                role=role,
                job_description=job_description,
                job_url=job_url,
                sender_profile=sender_profile,
                use_local_deepseek=True,
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                company_vertical=company.vertical if company else None
            )

        outreach.ds_wedge = result.get("ds_wedge")
        outreach.ds_rationale = result.get("ds_rationale")
        outreach.ds_key_points = result.get("ds_key_points", [])
        outreach.ds_raw_draft = result.get("ds_raw_draft")

        new_email = result.get("px_final_email")
        if new_email:
            outreach.px_final_email = new_email
            
        outreach.px_confidence = result.get("px_confidence")
        outreach.px_factual_flags = result.get("px_factual_flags", [])
        outreach.px_citations = result.get("px_citations", [])

        px_confidence = result.get("px_confidence", 0)
        px_flags = result.get("px_factual_flags", [])
        if px_confidence >= 0.85 and not px_flags:
            outreach.status = "ready"

        session.commit()
        st.success("✅ Full V2 Pipeline complete! Both stages finished.")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Full pipeline failed: {e}")
        st.exception(e)

# --- MAIN UI ---
def main():
    session = get_session()
    
    # Export functionality in sidebar
    with st.sidebar:
        st.markdown("### 📦 Export Codebase")
        st.caption("💡 Click ⬅️ to collapse sidebar")
        st.caption("Full or incremental export → SCP to Windows Downloads")
        st.markdown("---")

        def _do_export(incremental: bool):
            with st.spinner("Creating archive and transferring via SCP..." if not incremental else "Creating incremental archive and transferring via SCP..."):
                r = run_export_and_transfer(incremental=incremental, auto_scp=True, windows_username="chris")
            if r["error"]:
                st.error(r["error"])
                return
            st.session_state["export_zip_path"] = r["zip_path"]
            st.session_state["export_zip_filename"] = os.path.basename(r["zip_path"])
            st.session_state["export_zip_size"] = r["size_mb"]
            st.session_state["export_scp_command"] = r["scp_command"]
            st.session_state["export_scp_success"] = r["scp_success"]
            st.session_state["export_n_files"] = r.get("n_files")
            try:
                with open(r["zip_path"], "rb") as f:
                    st.session_state["export_zip_data"] = f.read()
            except Exception:
                st.session_state["export_zip_data"] = None
            if r["scp_success"]:
                st.success(f"✅ Export created and transferred to Windows Downloads ({r['size_mb']:.2f} MB)")
                st.balloons()
            else:
                st.warning(f"✅ Export created ({r['size_mb']:.2f} MB) — SCP failed. Use download or run command below.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Create Export", type="primary", use_container_width=True, help="Full export, then SCP to C:\\Users\\chris\\Downloads"):
                _do_export(incremental=False)
        with c2:
            has_last = get_last_export_timestamp() is not None
            if st.button(
                "🔄 Incremental Export",
                type="secondary",
                use_container_width=True,
                disabled=not has_last,
                help="Only changes since last full export" + (" (run full export first)" if not has_last else ""),
            ):
                _do_export(incremental=True)

        if "export_zip_path" in st.session_state:
            st.markdown("---")
            st.markdown("### Download")
            fn = st.session_state.get("export_zip_filename", "export.zip")
            sz = st.session_state.get("export_zip_size", 0)
            n = st.session_state.get("export_n_files")
            if n is not None:
                st.caption(f"Incremental: {n} file(s) · {sz:.2f} MB")
            else:
                st.caption(f"Full export · {sz:.2f} MB")
            zip_data = st.session_state.get("export_zip_data")
            if zip_data is not None:
                st.download_button(
                    label="📥 Download Export",
                    data=zip_data,
                    file_name=fn,
                    mime="application/zip",
                    use_container_width=True,
                    type="primary",
                )
            scp_cmd = st.session_state.get("export_scp_command")
            if scp_cmd:
                with st.expander("🔧 SCP command (run on Windows)", expanded=not st.session_state.get("export_scp_success")):
                    st.code(scp_cmd, language="bash")
            if st.button("🗑️ Clear Export", use_container_width=True):
                for k in ["export_zip_data", "export_zip_filename", "export_zip_path", "export_zip_size", "export_scp_command", "export_scp_success", "export_n_files"]:
                    st.session_state.pop(k, None)
                st.rerun()

        st.markdown("---")
        st.caption("💾 Excludes: databases, logs, cache, and large data files")
    
    # 3-Column Layout with independent scrolling
    col_queue, col_editor, col_insights = st.columns([1, 2, 1], gap="small")

    # === LEFT: QUEUE ===
    with col_queue:
        st.header("Inbox")
        
        # Filters
        filter_options = st.multiselect(
            "Filter Queue:",
            ['Job Applications', 'Signal Outreaches', 'Follow-ups'],
            default=['Job Applications', 'Signal Outreaches', 'Follow-ups']
        )
        
        queue_items = get_queue(session, filter_options)
        st.caption(f"{len(queue_items)} items due")
        
        # List with fit score chips (text-only labels for radio)
        if queue_items:
            # Create options with formatted labels
            options_list = []
            for idx, item in enumerate(queue_items):
                score = item.fit_score or 0
                
                # Color-coded score indicator
                if score >= 80:
                    score_indicator = f"🟢 {score}"
                elif score >= 60:
                    score_indicator = f"🟡 {score}"
                else:
                    score_indicator = f"⚪ {score}"
                
                # Type icon
                if item.lead_type == 'job_posting':
                    icon = "💼"
                elif item.lead_type == 'signal_only':
                    icon = "📡"
                else:
                    icon = "↩️" if 'followup' in str(item.outreach_type) else "❓"
                
                # Company name
                company_name = item.company.name if item.company else 'Unknown'
                
                # Build label
                label = f"{score_indicator} {icon} {company_name}"
                options_list.append((label, item.id))
            
            # Create dict for radio (label -> id)
            options_dict = {label: item_id for label, item_id in options_list}
            
            selected_label = st.radio(
                "Select Outreach:",
                options=list(options_dict.keys()),
                label_visibility="collapsed"
            )
            selected_id = options_dict.get(selected_label) if selected_label else None
        else:
            st.info("No items in queue")
            selected_id = None

    # Get selected item
    if selected_id:
        outreach = session.query(ProactiveOutreach).get(selected_id)
        company = outreach.company
        contact = outreach.contact
        job = session.query(Job).get(outreach.job_id) if outreach.job_id else None
        
        # === MIDDLE: EDITOR ===
        with col_editor:
            # Vertical Divider Visualization (Hack via Border)
            st.markdown("""<div style="border-left: 2px solid #ddd; height: 100%; position: absolute; left: 0;"></div>""", unsafe_allow_html=True)
            
            st.subheader(f"{company.name}")
            if job:
                st.markdown(f"**Role:** [{job.title}]({job.url})")
            
            # Editor (use px_final_email if available, else draft_email)
            email_body = outreach.px_final_email or outreach.draft_email or ""
            new_draft = st.text_area(
                "Draft Email", 
                value=email_body, 
                height=500,
                key=f"editor_{selected_id}"
            )
            
            # Update appropriate field if changed
            if new_draft != email_body:
                if outreach.px_final_email is not None:
                    outreach.px_final_email = new_draft
                else:
                    outreach.draft_email = new_draft
                session.commit()

            # Actions Row
            c1, c2, c3, c4, c5 = st.columns(5)
            
            # 1. Open in Mail Client
            mailto_link = build_mailto(outreach, contact)
            if mailto_link:
                c1.markdown(f'<a href="{mailto_link}" target="_blank" style="text-decoration:none;"><button style="width:100%; padding:10px; background:#eee; border:1px solid #ccc; border-radius:5px;">📧 Open Mail</button></a>', unsafe_allow_html=True)
            else:
                c1.button("No Email", disabled=True)

            # 2. Sent (with Mailgun integration)
            if c2.button("🚀 Send via Mailgun", key="btn_send_mailgun"):
                if contact and contact.email:
                    # Choose sender address
                    sender_key = choose_sender_address(company.name, contact.name)
                    
                    # Prepare email
                    subject = f"Connecting - {contact.name}"
                    if job:
                        subject = f"Regarding {company.name} - {job.title}"
                    
                    # Send via Mailgun
                    result = send_email_via_mailgun(
                        to_email=contact.email,
                        subject=subject,
                        body=new_draft,
                        sender_key=sender_key,
                        tags=['outreach', outreach.outreach_type]
                    )
                    
                    if result.get('success'):
                        outreach.status = 'sent'
                        outreach.sent_at = datetime.utcnow()
                        # Create Follow-up Task
                        if 'intro' in outreach.outreach_type:
                            followup = ProactiveOutreach(
                                id=str(uuid.uuid4()),
                                company_id=outreach.company_id,
                                contact_id=outreach.contact_id,
                                job_id=outreach.job_id,
                                outreach_type='followup_1',
                                status='queued',
                                next_action_at=datetime.utcnow() + timedelta(days=4),
                                fit_score=outreach.fit_score
                            )
                            session.add(followup)
                        st.success(f"✅ Email sent via Mailgun ({result.get('sender')})!")
                    else:
                        st.error(f"❌ Failed to send: {result.get('error')}")
                    
                    session.commit()
                    st.rerun()
                else:
                    st.warning("No contact email available")
            
            if c3.button("✅ Mark Sent", key="btn_sent"):
                outreach.status = 'sent'
                outreach.sent_at = datetime.utcnow()
                # Create Follow-up Task
                if 'intro' in outreach.outreach_type:
                    followup = ProactiveOutreach(
                        id=str(uuid.uuid4()),
                        company_id=outreach.company_id,
                        contact_id=outreach.contact_id,
                        job_id=outreach.job_id,
                        outreach_type='followup_1',
                        status='queued',
                        next_action_at=datetime.utcnow() + timedelta(days=4),
                        fit_score=outreach.fit_score
                    )
                    session.add(followup)
                    st.toast("Marked Sent & Scheduled Follow-up!")
                else:
                    st.toast("Marked Sent!")
                
                session.commit()
                st.rerun()

            # 4. Replied (removes from queue)
            if c4.button("✅ Replied", key="btn_reply"):
                outreach.status = 'replied'
                outreach.next_action_at = None
                session.commit()
                st.rerun()

            # 5. Dismiss (removes from queue)
            if c5.button("❌ Dismiss", key="btn_dismiss"):
                outreach.status = 'dismissed'
                outreach.next_action_at = None
                session.commit()
                st.rerun()

        # === RIGHT: ANALYSIS ===
        with col_insights:
            st.header("Analysis")

            st.markdown("### ⚡ V2 Pipeline Actions")
            btn_col1, btn_col2 = st.columns(2)

            with btn_col1:
                if st.button("🧠 Run DeepSeek (Stage 1)", key="btn_deepseek",
                             use_container_width=True,
                             help="Local analysis + draft (FREE)"):
                    run_deepseek_stage(outreach, company, contact, job, session)

            with btn_col2:
                ds_wedge = getattr(outreach, "ds_wedge", None)
                if st.button("🌐 Run Perplexity (Stage 2)", key="btn_perplexity",
                             use_container_width=True,
                             disabled=not ds_wedge,
                             help="Web verification + finalize (~1¢)"):
                    run_perplexity_stage(outreach, company, contact, job, session)

            if st.button("🚀 Run Full V2 Pipeline", key="btn_full_pipeline",
                         use_container_width=True, type="primary",
                         help="Run both stages sequentially"):
                run_full_v2_pipeline(outreach, company, contact, job, session)

            st.markdown("---")

            # Check if V2 pipeline data exists
            has_v2 = outreach.ds_wedge or outreach.px_final_email
            has_legacy = outreach.insights or outreach.draft_email
            
            if has_v2:
                # V2 PIPELINE: Two-Stage Display
                st.markdown("### 🧠 DeepSeek Strategy")
                
                if outreach.ds_wedge:
                    st.markdown(f"**Wedge:** `{outreach.ds_wedge}`")
                    
                    if outreach.ds_rationale:
                        with st.expander("📋 Rationale"):
                            st.markdown(outreach.ds_rationale)
                    
                    ds_key_points = getattr(outreach, "ds_key_points", [])
                    # Normalize to list
                    if isinstance(ds_key_points, str):
                        ds_key_points = [ds_key_points]
                    elif ds_key_points is None:
                        ds_key_points = []

                    if ds_key_points:
                        with st.expander("✓ Proof Points"):
                            for point in ds_key_points:
                                st.markdown(f"- {point}")
                    
                    if outreach.ds_raw_draft:
                        with st.expander("📝 DeepSeek Draft"):
                            st.text_area("First draft", value=outreach.ds_raw_draft, height=200, disabled=True)
                
                st.markdown("---")
                st.markdown("### 🌐 Perplexity Final")
                
                if outreach.px_confidence:
                    conf = float(outreach.px_confidence)
                    conf_pct = int(conf * 100)
                    if conf >= 0.85: badge = f"🟢 {conf_pct}% High"
                    elif conf >= 0.70: badge = f"🟡 {conf_pct}% Medium"
                    else: badge = f"🔴 {conf_pct}% Low"
                    st.markdown(f"**Confidence:** {badge}")
                
                px_factual_flags = getattr(outreach, "px_factual_flags", None)

                # Normalize to list
                if isinstance(px_factual_flags, str):
                    px_factual_flags = [px_factual_flags]
                elif px_factual_flags is None:
                    px_factual_flags = []

                if px_factual_flags:
                    with st.expander(f"⚠️ Flags ({len(px_factual_flags)})", expanded=True):
                        for flag in px_factual_flags:
                            st.warning(flag)
                else:
                    st.success("✅ No factual flags")
                
                px_citations = getattr(outreach, "px_citations", [])
                # Normalize to list
                if isinstance(px_citations, str):
                    px_citations = [px_citations]
                elif px_citations is None:
                    px_citations = []

                if px_citations:
                    with st.expander("📚 Citations"):
                        for i, cit in enumerate(px_citations, 1):
                            st.caption(f"{i}. {cit}")
                
            elif has_legacy:
                # LEGACY: Council (Deprecated)
                with st.expander("🧙‍♂️ Legacy Council (Deprecated)", expanded=True):
                    if outreach.insights:
                        st.markdown(outreach.insights)
                    else:
                        st.info("No council insights")
                st.caption("💡 Regenerate with V2 pipeline for web-verified facts")
            
            else:
                st.info("No analysis yet")
            
            # 2. Strategy Context (always show)
            with st.expander("Strategy", expanded=False):
                st.metric("Fit Score", value=outreach.fit_score)
                if outreach.fit_explanation:
                    st.markdown(f"**Angle:** {outreach.fit_explanation}")
                if outreach.signal_summary:
                    st.markdown(f"**Signal:** {outreach.signal_summary}")

            # 3. Contact & Company (always show)
            with st.expander("Target Info", expanded=False):
                if contact:
                    st.markdown(f"**{contact.name}**")
                    st.caption(contact.title)
                    st.caption(contact.email)
                st.divider()
                st.markdown(f"**{company.name}**")
                st.caption(f"{company.vertical} | {company.hq_location}")
                if company.linkedin_url:
                    st.markdown(f"[LinkedIn]({company.linkedin_url})")

    else:
        with col_editor:
            st.info("🎉 You're all caught up! No items in the queue.")

    session.close()

if __name__ == "__main__":
    main()
