import logging
from database import SessionLocal
from models import Company, CompanySignal, ProactiveOutreach, Contact
from utils import call_llm, parse_json_from_llm
import config
import requests
import re
from datetime import datetime
import time
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_news_for_company(company_name: str) -> List[Dict[str, Any]]:
    if not config.NEWS_API_KEY or 'your_' in config.NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": f'"{company_name}"', "sortBy": "publishedAt", "pageSize": 5, "apiKey": config.NEWS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200: return resp.json().get('articles', [])
    except: pass
    return []

def fetch_google_news_rss(company_name: str) -> List[Dict[str, Any]]:
    query = f'"{company_name}"'
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        items = []
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            pub_date = item.findtext("pubDate") or ""
            if title and link:
                items.append({"title": title, "url": link, "published_at": pub_date})
        return items
    except Exception:
        return []

def fetch_google_cse(company_name: str) -> List[Dict[str, Any]]:
    if not config.GOOGLE_API_KEY or not getattr(config, "GOOGLE_CSE_ID", None):
        return []
    query = f'"{company_name}" (appoints OR names OR hires OR "joins as" OR "joins" OR promoted) (CRO OR "Chief Revenue Officer" OR "Chief Commercial Officer" OR "VP Sales" OR "Head of Sales" OR "VP Partnerships")'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": config.GOOGLE_API_KEY,
        "cx": config.GOOGLE_CSE_ID,
        "q": query,
        "num": 5
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = []
        for item in data.get("items", []):
            title = item.get("title") or ""
            link = item.get("link") or ""
            snippet = item.get("snippet") or ""
            if title and link:
                items.append({"title": title, "url": link, "snippet": snippet})
        return items
    except Exception:
        return []

def fetch_lux_search(company_name: str) -> List[Dict[str, Any]]:
    if not config.LUX_API_KEY or not getattr(config, "LUX_API_URL", None):
        return []
    try:
        resp = requests.get(
            config.LUX_API_URL,
            params={"q": company_name, "api_key": config.LUX_API_KEY, "limit": 5},
            timeout=10
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        candidates = data.get("results") or data.get("items") or data.get("data") or []
        items = []
        for item in candidates:
            title = item.get("title") or item.get("name") or ""
            url = item.get("url") or item.get("link") or item.get("source_url") or ""
            snippet = item.get("snippet") or item.get("description") or ""
            if title and url:
                items.append({"title": title, "url": url, "snippet": snippet})
        return items
    except Exception:
        return []

def fetch_job_signals(company: Company) -> List[Dict[str, Any]]:
    from jobspy import scrape_jobs
    try:
        jobs = scrape_jobs(
            site_name=getattr(config, "JOBSPY_SITES", ["linkedin", "indeed"]),
            search_term=f'"{company.name}" sales',
            results_wanted=5,
            hours_old=168
        )
        if not jobs.empty: return jobs.to_dict('records')
    except: pass
    return []

def _normalize_slug(name: str) -> str:
    if not name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug

def fetch_ats_role_signals(company: Company) -> List[Dict[str, Any]]:
    if not getattr(config, "ENABLE_AGGRESSIVE_SCRAPING", True):
        return []
    slug = _normalize_slug(company.name or "")
    targets = set(getattr(config, "GREENHOUSE_TARGETS", []) or [])
    if slug not in targets:
        return []
    try:
        from scraper_ats import scrape_greenhouse_company, scrape_lever_company
    except Exception:
        return []
    signals = []
    for job in (scrape_greenhouse_company(slug) + scrape_lever_company(slug)):
        title = (job.get("title") or "").strip()
        url = job.get("url") or ""
        if not title or not url:
            continue
        roles = extract_gtm_roles(title)
        if roles:
            for role in roles:
                signals.append(build_role_signal(title, url, role, "ats_direct", "posting"))
        else:
            signals.append({"text": f"Hiring for: {title}", "url": url, "type": "hiring"})
    return signals

GTM_ROLE_PATTERNS = [
    (r"\bchief revenue officer\b|\bcro\b", "CRO"),
    (r"\bchief commercial officer\b|\bcco\b", "Chief Commercial Officer"),
    (r"\bhead of sales\b|\bhead of revenue\b", "Head of Sales"),
    (r"\bvp sales\b|\bvice president sales\b|\bsvp sales\b", "VP Sales"),
    (r"\bvp revenue\b|\bvp of revenue\b", "VP Revenue"),
    (r"\bvp partnerships\b|\bhead of partnerships\b", "VP Partnerships"),
    (r"\bvp business development\b|\bhead of business development\b", "VP Business Development"),
    (r"\bdirector of sales\b|\bregional vice president\b", "Director of Sales"),
    (r"\benterprise account executive\b|\bstrategic account executive\b", "Strategic AE"),
]

NEW_ROLE_ACTION_RE = re.compile(r"\b(appoints|names|hires|hired|joins|joining|promotes|promoted|elevates|taps|brings on|recruits)\b", re.IGNORECASE)
ROLE_POSTING_RE = re.compile(r"\b(hiring|opening|role|position|job)\b", re.IGNORECASE)

ROLE_URGENCY = {
    "CRO": 85,
    "Chief Commercial Officer": 80,
    "Head of Sales": 78,
    "VP Sales": 72,
    "VP Revenue": 70,
    "VP Partnerships": 65,
    "VP Business Development": 62,
    "Director of Sales": 55,
    "Strategic AE": 50
}

def extract_gtm_roles(text: str) -> List[str]:
    roles = []
    for pattern, label in GTM_ROLE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            roles.append(label)
    return list(dict.fromkeys(roles))

def build_role_signal(text: str, url: str, role: str, source: str, kind: str) -> Dict[str, Any]:
    urgency = ROLE_URGENCY.get(role, 55)
    signal_type = "new_role_announcement" if kind == "announcement" else "new_role_posting"
    tag = "New role announcement" if kind == "announcement" else "New role posting"
    return {
        "text": f"{tag}: {role}. {text}",
        "url": url,
        "type": signal_type,
        "urgency": urgency,
        "role": role,
        "source": source
    }

def rule_score_signal(sig: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if sig.get("type") in {"new_role_announcement", "new_role_posting"}:
        urgency = int(sig.get("urgency") or 60)
        return {
            "is_trigger": urgency >= 50,
            "urgency_score": urgency,
            "signal_type": sig.get("type")
        }
    return None

def generate_role_aware_email(company, signal_text, contact):
    """Generate a draft email tailored to the recipient's role."""
    role = contact.role_type
    from utils.email_safety import strip_unresolved_placeholders, sanitize_email_text
    signal_text = strip_unresolved_placeholders(signal_text or "")
    prompt = f"""
    Create a highly personalized outreach email for a senior enterprise sales role.
    Target: {contact.name} ({contact.title}) at {company.name}.
    Context: {signal_text}
    Role Category: {role}
    
    Instructions by Role Category:
    - Founder/CEO: Emphasize "helping you build/scale payer GTM" and "hands-on seller who can own revenue and build motion."
    - CRO/VP Sales: Emphasize "quota-carrying senior IC / player-coach" and specific payer deals.
    - CCO/COO/Other Executive: Emphasize "cross-functional GTM, payer relationships, and implementation awareness."
    
    Candidate Background: {config.USER_PROFILE_SUMMARY}
    
    CONSULTATIVE TONE (CRITICAL):
    Write as a SENIOR PEER offering perspective, NOT a consultant prescribing solutions.
    - Use QUESTIONS about their challenges: "Is that the phase you're in?" "Am I reading this right?"
    - Frame observations tentatively: "My sense is..." "It seems like..." "Based on what I'm seeing..."
    - AVOID prescriptions: Don't say "will be key" or "must focus on" or "needs to"
    - INVITE DIALOGUE: End with one question that invites response
    - Show expertise through insightful questions, not assertions
    - Avoid startup or VC metaphors and abstraction phrases. Use plain operational language.
    - Do NOT reference job postings, role descriptions, or hiring language.
    - Include at most ONE strategic question in the body.
    - Place the single strategic question in the first third of the email.
    - Do NOT use contrastive constructions ("not X but Y", "less/more", "wasn't X - it was Y"). State the key constraint directly without negating an alternative.

    GOLD EXAMPLE (style and structure only; do not copy facts unless provided):
    Subject: Thoughts on scaling US sales post your Series B

    Hi,

    Congrats on the $65M Series B in October. Having followed Heidi's growth from Australia to powering 10M+ consults monthly, my read is that the US expansion hinges on translating a strong enterprise sales motion from a relatively unified system like the NHS into a market where care delivery models, clinical workflows, and contracting structures vary widely across providers and payers. Am I reading that right?

    In similar US expansions I've worked on, the friction showed up in mapping a single product narrative across very different clinical environments and risk-based contracts without fragmenting the sales motion or over-customizing. I've led teams closing 7-figure Medicaid and Medicare Advantage deals where that translation work often determined whether pilots turned into durable, multi-year revenue.

    If that's the problem space you're navigating, I'm happy to share what proved durable in those ramps.
    
    WRITING MECHANICS:
    - Use ONLY standard punctuation: periods, commas, regular hyphens (-), question marks, exclamation points
    - NEVER use em dashes (—) or en dashes (–) - these are AI content giveaways
    - Avoid overly formal openings like "I trust this finds you well"
    - Write naturally as a human would, use contractions (I've, we've, that's)
    
    Return JSON:
    {{
      "outreach_angle": "string summary of the pitch",
      "draft_email": "string text of the email"
    }}
    """
    resp = call_llm(prompt, response_format="json", temperature=0.25)
    parsed = parse_json_from_llm(resp)
    if isinstance(parsed, dict) and parsed.get("draft_email"):
        parsed["draft_email"] = sanitize_email_text(parsed["draft_email"])
    return parsed

def score_signal(company: Company, signal_text: str):
    prompt = f"""
    Evaluate this signal for {company.name} ({company.vertical}).
    Signal: {signal_text}
    Determine if this is an outreach trigger (High urgency = Funding, Expansion, New Leadership Hire, or multiple new postings).
    Return JSON: {{"is_trigger": bool, "urgency_score": 0-100, "signal_type": "string"}}
    """
    resp = call_llm(prompt, response_format="json")
    return parse_json_from_llm(resp)

def run_signal_monitor(max_companies_override: Optional[int] = None):
    db = SessionLocal()
    try:
        start_time = time.time()
        max_companies = (
            max_companies_override
            if max_companies_override is not None
            else int(config.SIGNAL_MONITOR_MAX_COMPANIES or 0)
        )
        max_signals = int(config.SIGNAL_MONITOR_MAX_SIGNALS_PER_COMPANY or 0)
        disable_llm = (config.SIGNAL_MONITOR_DISABLE_LLM or "").strip().lower() == "true"

        active_companies = (
            db.query(Company)
            .filter(Company.monitoring_status == "active")
            .all()
        )
        total = len(active_companies)
        if max_companies > 0:
            active_companies = active_companies[:max_companies]

        logger.info(
            f"[Agent2] Starting. companies={len(active_companies)} (of {total}), "
            f"max_signals_per_company={max_signals or 'all'}, disable_llm={disable_llm}"
        )

        total_new_signals = 0
        total_outreaches = 0
        for idx, company in enumerate(active_companies, start=1):
            company_start = time.time()
            logger.info(f"[Agent2] Company {idx}/{len(active_companies)}: {company.name}")
            signals_found = []
            
            # 1. News
            articles = fetch_news_for_company(company.name)
            for art in articles:
                text = art.get("title") or ""
                url = art.get("url") or ""
                roles = extract_gtm_roles(text)
                if roles and NEW_ROLE_ACTION_RE.search(text):
                    for role in roles:
                        signals_found.append(build_role_signal(text, url, role, "newsapi", "announcement"))
                else:
                    signals_found.append({"text": text, "url": url, "type": "news"})

            # 1b. Google News RSS (more aggressive coverage)
            rss_items = fetch_google_news_rss(company.name)
            for item in rss_items:
                text = item.get("title") or ""
                url = item.get("url") or ""
                roles = extract_gtm_roles(text)
                if roles and NEW_ROLE_ACTION_RE.search(text):
                    for role in roles:
                        signals_found.append(build_role_signal(text, url, role, "google_news_rss", "announcement"))
                else:
                    signals_found.append({"text": text, "url": url, "type": "news"})

            # 1c. Google CSE (if configured)
            cse_items = fetch_google_cse(company.name)
            for item in cse_items:
                text = item.get("title") or ""
                url = item.get("url") or ""
                snippet = item.get("snippet") or ""
                combined = f"{text}. {snippet}".strip()
                roles = extract_gtm_roles(combined)
                if roles and NEW_ROLE_ACTION_RE.search(combined):
                    for role in roles:
                        signals_found.append(build_role_signal(text, url, role, "google_cse", "announcement"))
                else:
                    signals_found.append({"text": combined, "url": url, "type": "news"})

            # 1d. Lux search (if configured)
            lux_items = fetch_lux_search(company.name)
            for item in lux_items:
                text = item.get("title") or ""
                url = item.get("url") or ""
                snippet = item.get("snippet") or ""
                combined = f"{text}. {snippet}".strip()
                roles = extract_gtm_roles(combined)
                if roles and NEW_ROLE_ACTION_RE.search(combined):
                    for role in roles:
                        signals_found.append(build_role_signal(text, url, role, "lux", "announcement"))
                else:
                    signals_found.append({"text": combined, "url": url, "type": "news"})
            
            # 2. Jobs
            jobs = fetch_job_signals(company)
            if jobs:
                for job in jobs[:3]:
                    title = (job.get("title") or "").strip()
                    url = job.get("job_url") or job.get("url") or ""
                    if not title or not url:
                        continue
                    roles = extract_gtm_roles(title)
                    if roles:
                        for role in roles:
                            signals_found.append(build_role_signal(title, url, role, "jobspy", "posting"))
                    else:
                        signals_found.append({"text": f"Hiring for: {title}", "url": url, "type": "hiring"})

            # 2b. Aggressive ATS scraping (direct boards)
            ats_signals = fetch_ats_role_signals(company)
            if ats_signals:
                signals_found.extend(ats_signals)

            logger.info(f"[Agent2]   {company.name}: {len(signals_found)} raw signals")
            processed = 0
            for sig in signals_found:
                if max_signals and processed >= max_signals:
                    break
                processed += 1

                sig_text = sig.get("text", "")
                sig_url = sig.get("url", "")
                sig_type = sig.get("type", "unknown")

                if disable_llm:
                    logger.info(f"[Agent2]   (no-LLM) raw signal: {sig_type} | {(sig_text or '')[:80]}...")
                    continue

                existing = db.query(CompanySignal).filter(CompanySignal.source_url == sig_url).first()
                if existing:
                    continue

                from scoring import score_signal_lead
                existing_signals = db.query(CompanySignal).filter(
                    CompanySignal.company_id == company.id
                ).all()
                rules_score = score_signal_lead(company, existing_signals)
                analysis = rule_score_signal(sig)
                if not analysis:
                    analysis = score_signal(company, sig_text)
                if not analysis:
                    continue

                urgency_score = analysis.get("urgency_score", 0)
                final_fit_score = int(urgency_score * 0.5 + rules_score * 0.5)

                new_sig = CompanySignal(
                    company_id=company.id,
                    signal_type=analysis.get("signal_type", sig_type),
                    signal_date=datetime.now(),
                    signal_text=sig_text,
                    score=urgency_score,
                    source_url=sig_url,
                )
                db.add(new_sig)
                total_new_signals += 1

                if analysis.get("is_trigger") and urgency_score >= 50:
                    from models import LeadCategorizationAudit
                    audit = LeadCategorizationAudit(
                        company_name=company.name,
                        role_title=None,
                        job_url=sig_url,
                        signal_source="signal_monitor",
                        signal_only_detected=True,
                        final_lead_type="signal_only",
                    )
                    db.add(audit)
                    contact = (
                        db.query(Contact)
                        .filter(Contact.company_id == company.id)
                        .order_by(Contact.confidence_score.desc())
                        .first()
                    )
                    email_draft = {"outreach_angle": "Generic signal trigger", "draft_email": ""}
                    if contact:
                        email_draft = generate_role_aware_email(company, sig_text, contact)
                    outreach = ProactiveOutreach(
                        company_id=company.id,
                        contact_id=contact.id if contact else None,
                        signal_summary=email_draft.get("outreach_angle"),
                        fit_explanation=f"Trigger: {sig_text}",
                        draft_email=email_draft.get("draft_email"),
                        priority_score=urgency_score,
                        fit_score=final_fit_score,
                        lead_type="signal_only",
                        outreach_type="signal_intro",
                        status="queued",
                    )
                    db.add(outreach)
                    total_outreaches += 1

            db.commit()
            elapsed_company = time.time() - company_start
            logger.info(
                f"[Agent2]   {company.name}: done in {elapsed_company:.1f}s "
                f"(cumulative: {total_new_signals} signals, {total_outreaches} outreaches)"
            )
        elapsed = time.time() - start_time
        logger.info(f"[Agent2] Done. Elapsed {elapsed:.1f}s")
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Proactive opportunity signal monitor (Agent 2)")
    p.add_argument(
        "--max-companies",
        type=int,
        default=None,
        metavar="N",
        help="Limit to N companies (overrides SIGNAL_MONITOR_MAX_COMPANIES)",
    )
    args = p.parse_args()
    run_signal_monitor(max_companies_override=args.max_companies)
