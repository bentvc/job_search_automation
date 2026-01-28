"""
Agent 6: News-driven company discovery — Pull-to-Enrich staging.

Stage 1 (Collector): Broad, cheap discovery from NewsAPI/Google News. No Apollo.
  → Write-through: every extracted candidate persisted as status='discovered'.
  → prelim_vertical / preliminary_fit_score from cheap heuristic or LLM.

Stage 2 (Sieve): Pure evaluation. No Company, no Apollo, no contacts.
  → score_candidate(name, prelim_vertical, context) → prelim_fit_score, scored_at.
  → Reject Ops/Support/Enablement in context; score < threshold → rejected.
  → Else status='scored'. Single commit at end.

Stage 3 (Investor): Only status=='scored' and prelim_fit_score >= threshold.
  → Apollo → Company + signals; status='promoted', promoted_at set. One-way.
"""

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus

import requests
import xml.etree.ElementTree as ET

import config
from database import SessionLocal
from models import Company, CompanySignal, DiscoveryCandidate
from sqlalchemy import asc, desc, nulls_last, or_
from utils import call_llm, parse_json_from_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sieve: reject if context contains these (Revenue Role ONLY)
SIEVE_REJECT_PATTERNS = [
    r"sales\s*ops", r"sales\s*operations", r"enablement", r"revops", r"revenue\s*operations",
    r"customer\s*success\s*manager", r"\bcsm\b", r"implementation\s*manager", r"implementation\s*consultant",
    r"support\s*specialist", r"sales\s*admin", r"operations\s*coordinator",
]
SIEVE_REJECT_RE = re.compile("|".join(f"({p})" for p in SIEVE_REJECT_PATTERNS), re.IGNORECASE)

# Discovery bias: only pass articles that match ≥1 high-value trigger (before LLM)
HIGH_VALUE_TRIGGERS = [
    "raised $", "Series A", "Series B", "Series C", "growth", "expanding", "launches",
    "health plan", "payer", "Medicare Advantage", "employer health", "PBM",
    "value-based care", "risk adjustment", "utilization management", "Chief Revenue", "CRO",
    "hires", "appoints", "raises",
]
# Suppress articles that look like services/research/hospital noise
DISCOVERY_NEGATIVE = [
    "consulting", "research firm", "hospital system", "clinic ", "clinical research",
    "contract research organization", "CRO study", "clinical trial",
]
MAX_PER_ARTICLE = 3  # cap companies extracted per article (or per batch when batched)


def _article_text(art: Dict[str, Any]) -> str:
    t = (art.get("title") or "").strip()
    d = (art.get("description") or art.get("snippet") or "").strip()
    return f"{t} {d}".lower()


def filter_articles_by_triggers(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only articles that match ≥1 HIGH_VALUE_TRIGGER and none of DISCOVERY_NEGATIVE."""
    out = []
    for art in articles:
        text = _article_text(art)
        if any(n in text for n in DISCOVERY_NEGATIVE):
            continue
        if any(t in text for t in HIGH_VALUE_TRIGGERS):
            out.append(art)
    return out


# --- Topic-based fetchers (no company name) ---

def fetch_news_by_topic(query: str, page_size: int = 10) -> List[Dict[str, Any]]:
    if not getattr(config, "NEWS_API_KEY", None) or "your_" in str(config.NEWS_API_KEY):
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": query, "sortBy": "publishedAt", "pageSize": min(page_size, 100), "apiKey": config.NEWS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("articles", []) or []
    except Exception as e:
        logger.debug(f"NewsAPI topic fetch failed: {e}")
    return []


def fetch_google_news_rss_by_query(query: str, max_items: int = 10) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            if title and link:
                items.append({"title": title, "url": link, "snippet": desc, "description": desc})
        return items
    except Exception as e:
        logger.debug(f"Google News RSS topic fetch failed: {e}")
    return []


# --- Stage 1: Extract names + cheap preliminary_fit (no Apollo) ---

NAME_PATTERNS = [
    r"(?:^|\s)([A-Z][A-Za-z0-9&\s\-]{2,32})\s+(?:raises|raised|hires|hired|names?|appoints|announces)",
    r"(?:raises|raised|hires|hired|names?|appoints)\s+(?:[\w\s]+)\s+at\s+([A-Z][A-Za-z0-9&\s\-]{2,32})",
    r"([A-Z][A-Za-z0-9&\s\-]{2,32})\s+(?:raises|raised|Series\s+[A-Z]|hires|names)",
    r"(?:^|\s)([A-Z][A-Za-z0-9&\s\-]{2,32})\s*[–\-]\s*(?:raises|hires|Series)",
]
BAD_SUBSTRINGS = {"inc", "llc", "ltd", "news", "today", "week", "report", "source", "read more", "copyright"}


def extract_company_names_heuristic(articles: List[Dict[str, Any]], max_per_batch: int = 15) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for art in articles:
        if len(out) >= max_per_batch:
            break
        title = (art.get("title") or "").strip()
        snippet = (art.get("description") or art.get("snippet") or "").strip()
        url = art.get("url") or ""
        text = f"{title} {snippet}"
        for pat in NAME_PATTERNS:
            if len(out) >= max_per_batch:
                break
            for m in re.finditer(pat, text):
                name = (m.group(1) or "").strip()
                if len(name) < 3 or len(name) > 60:
                    continue
                low = name.lower()
                if any(b in low for b in BAD_SUBSTRINGS):
                    continue
                if name not in seen:
                    seen.add(name)
                    out.append({"company_name": name, "context": title[:200], "source_url": url, "discovery_rank": len(out) + 1})
    return out[:max_per_batch]


def extract_company_names_llm(articles: List[Dict[str, Any]], max_per_batch: Optional[int] = None) -> List[Dict[str, Any]]:
    """Ranked extraction: up to 5 companies most likely GTM-relevant, best first. Capped by max_per_batch (default 3 * len(articles) or 15)."""
    if not articles:
        return []
    cap = max_per_batch if max_per_batch is not None else min(15, MAX_PER_ARTICLE * max(1, len(articles)))
    batch = []
    for a in articles[:10]:
        t = (a.get("title") or "").strip()
        s = (a.get("description") or a.get("snippet") or "").strip()[:300]
        batch.append(f"T: {t}\nS: {s}")
    block = "\n\n".join(batch)
    prompt = f"""From the following news headlines/snippets, extract up to 5 company or startup names most likely to be high-growth, payer-aligned, or at a revenue-inflection point. Only return companies where the article implies commercial activity, growth, or go-to-market change (e.g. raised funding, hired CRO/VP Sales, launched product, expansion). Do not include competitors or brands mentioned only for comparison. Rank by estimated GTM relevance, best first. One per line, best first. If none imply budget/buying/revenue motion, output NONE.

{block}

Companies (best first, one per line):"""
    try:
        resp = call_llm(prompt, temperature=0.1)
        lines = [l.strip() for l in (resp or "").strip().splitlines() if l.strip()]
        if not lines or lines[0].upper() == "NONE":
            return []
        out = []
        seen = set()
        url = articles[0].get("url") or ""
        title = (articles[0].get("title") or "")[:200]
        for rank, name in enumerate(lines[:cap], start=1):
            if 3 <= len(name) <= 60 and name not in seen:
                seen.add(name)
                out.append({"company_name": name, "context": title, "source_url": url, "discovery_rank": rank})
        return out
    except Exception as e:
        logger.warning(f"LLM extraction failed: {e}")
    return []


def score_preliminary_fit_cheap(company_name: str, context: str, use_llm: bool) -> int:
    """Cheap 0–100 preliminary fit from context only (no Apollo)."""
    if not use_llm:
        low = f"{company_name} {context}".lower()
        if any(k in low for k in ["payer", "medicare", "medicaid", "health plan", "risk adjustment", "utilization management"]):
            return 75
        if any(k in low for k in ["health", "healthcare", "healthtech", "series b", "cro", "chief revenue"]):
            return 60
        if any(k in low for k in ["fintech", "insurance", "revenue"]):
            return 50
        return 30
    prompt = f"""Rate 0-100 how likely this company is a fit for someone selling to healthcare payers / health plans / fintech (no research, just from the snippet).
Company: {company_name}
Snippet: {context[:400]}

Reply with a single number 0-100, then a short reason in one line."""
    try:
        resp = call_llm(prompt, temperature=0.1)
        for part in (resp or "").replace(",", " ").split():
            if part.isdigit():
                return min(100, max(0, int(part)))
    except Exception:
        pass
    return 30


def _infer_prelim_vertical(company_name: str, context: str) -> str:
    """Cheap heuristic vertical from name+context for Stage 1."""
    low = f"{company_name} {context}".lower()
    if any(k in low for k in ["payer", "medicare", "medicaid", "health plan", "risk adjustment"]):
        return "healthcare_payer"
    if any(k in low for k in ["health", "healthcare", "healthtech", "series b", "cro"]):
        return "healthcare_general"
    if any(k in low for k in ["fintech", "insurance", "payment"]):
        return "fintech"
    return ""


def compute_discovery_score_heuristic(context: str, prelim_vertical: str) -> int:
    """Pre-sieve heuristic: bias toward Series/payer/employer. Not a replacement for Stage 2 scoring."""
    score = 0
    low = (context or "").lower()
    vert = (prelim_vertical or "").lower()
    if "series" in low:
        score += 20
    if any(k in vert for k in ["payer", "healthcare_payer"]) or any(
        k in low for k in ["payer", "medicare advantage", "ma ", "pbm", "health plan"]
    ):
        score += 30
    if "employer" in low:
        score += 10
    return score


ENTITY_CONFIDENCE_THRESHOLD = 70  # 0–100; below this → reject in Stage 1.5


def _normalize_name(s: str) -> str:
    """Strip leading 'N. ' list prefixes for matching."""
    if not s:
        return ""
    return re.sub(r"^\d+\.\s*", "", (s or "").strip()).strip()


def resolve_entity_llm(article_context: str, company_names: List[str]) -> Dict[str, Any]:
    """LLM entity resolution: who is the single primary commercial actor? Returns {primary_company: {name, confidence}, secondary_mentions, reasoning}."""
    if not company_names:
        return {"primary_company": {"name": "", "confidence": 0}, "secondary_mentions": [], "reasoning": ""}
    names_block = "\n".join(f"- {n}" for n in company_names[:15])
    prompt = f"""You are performing entity resolution for business news.

Given an article and a list of extracted company names, determine:
1. The single primary company whose commercial activity is the subject (launching, hiring, raising, selling).
2. Any other companies mentioned only for context or comparison.

Rules:
- Choose one primary company only.
- If multiple are equally central, choose the one taking action.
- Ignore competitors, customers, partners unless they are the actor.

Article/snippet:
{article_context[:800]}

Extracted names:
{names_block}

Return JSON only with:
- primary_company: {{"name": "<exact company name>", "confidence": 0.0–1.0}}
- secondary_mentions: ["name1", "name2"]
- reasoning: one sentence
"""
    try:
        resp = call_llm(prompt, response_format="json", temperature=0.1)
        out = parse_json_from_llm(resp) or {}
        primary = out.get("primary_company") or {}
        name = (primary.get("name") or "").strip()
        conf = primary.get("confidence")
        if isinstance(conf, (int, float)):
            conf = max(0, min(1, float(conf)))
        else:
            conf = 0.8
        return {
            "primary_company": {"name": name, "confidence": conf},
            "secondary_mentions": list(out.get("secondary_mentions") or []),
            "reasoning": str(out.get("reasoning") or ""),
        }
    except Exception as e:
        logger.warning(f"Entity resolution LLM failed: {e}")
        # fallback: first name as primary
        first = (company_names[0] or "").strip()
        return {"primary_company": {"name": first, "confidence": 0.5}, "secondary_mentions": company_names[1:], "reasoning": "fallback"}


def stage1_5_entity_resolution(confidence_threshold: int = ENTITY_CONFIDENCE_THRESHOLD) -> int:
    """Stage 1.5: Entity cleansing. Group by source_url, resolve primary actor per article; reject secondaries and low-confidence. Sets canonical_company_name, entity_confidence."""
    db = SessionLocal()
    use_llm = not getattr(config, "NEWS_DISCOVERY_DISABLE_LLM", False)
    updated = 0
    try:
        rows = (
            db.query(DiscoveryCandidate)
            .filter(DiscoveryCandidate.status.in_(["discovered", "pending"]), DiscoveryCandidate.entity_confidence.is_(None))
            .all()
        )
        if not rows or not use_llm:
            return 0
        by_url: Dict[str, List[DiscoveryCandidate]] = {}
        for r in rows:
            url = (r.source_url or "").strip() or "__none__"
            by_url.setdefault(url, []).append(r)
        for url, group in by_url.items():
            if url == "__none__" or not group:
                continue
            ctx = (group[0].context or "")[:800]
            names = list({(r.company_name or "").strip() for r in group if (r.company_name or "").strip()})
            if not names:
                continue
            res = resolve_entity_llm(ctx, names)
            primary_name = (res["primary_company"].get("name") or "").strip()
            conf_01 = res["primary_company"].get("confidence", 0.8)
            conf_100 = int(round(conf_01 * 100))
            secondaries = {_normalize_name(s).lower() for s in (res.get("secondary_mentions") or [])}
            primary_norm = _normalize_name(primary_name).lower()
            for r in group:
                r.canonical_company_name = primary_name or r.company_name
                name_norm = _normalize_name(r.company_name or "").lower()
                if name_norm == primary_norm or (primary_norm and primary_norm in name_norm and len(primary_norm) >= 4):
                    r.entity_confidence = conf_100
                    if conf_100 < confidence_threshold:
                        r.status = "rejected"
                        r.rejected_reason = f"Entity confidence {conf_100} < {confidence_threshold}"
                else:
                    r.entity_confidence = 0
                    r.status = "rejected"
                    r.rejected_reason = "Secondary mention / not primary commercial actor"
                updated += 1
        db.commit()
        logger.info(f"[Agent6 Stage1.5] Entity resolution done; {updated} candidates processed (secondary/low-confidence rejected).")
    finally:
        db.close()
    return updated


def stage1_collect(
    max_articles_per_query: Optional[int] = None,
    use_llm_extraction: bool = True,
    use_llm_preliminary: bool = False,
) -> int:
    """Stage 1: Fetch news, extract names, cheap prelim. Write-through: every extracted candidate persisted as status='discovered'. No Apollo."""
    db = SessionLocal()
    max_art = max_articles_per_query or getattr(config, "NEWS_DISCOVERY_MAX_ARTICLES_PER_QUERY", 10)
    queries = getattr(config, "NEWS_DISCOVERY_QUERIES", [])
    use_llm = use_llm_extraction and not getattr(config, "NEWS_DISCOVERY_DISABLE_LLM", False)
    added = 0
    try:
        for q in queries:
            arts_news = fetch_news_by_topic(q, page_size=max_art)
            arts_rss = fetch_google_news_rss_by_query(q, max_items=max_art)
            articles = (arts_news or []) + (arts_rss or [])
            for a in articles:
                if "url" not in a and "link" in a:
                    a["url"] = a["link"]
                if "description" not in a and "snippet" in a:
                    a["description"] = a["snippet"]
            articles = filter_articles_by_triggers(articles)
            cap = min(15, MAX_PER_ARTICLE * max(1, len(articles)))
            candidates = (
                extract_company_names_llm(articles, max_per_batch=cap)
                if use_llm
                else extract_company_names_heuristic(articles, max_per_batch=cap)
            )
            for c in candidates:
                name = (c.get("company_name") or "").strip()
                context = c.get("context") or ""
                url = c.get("source_url") or ""
                if not name:
                    continue
                existing = db.query(DiscoveryCandidate).filter(
                    DiscoveryCandidate.company_name.ilike(name),
                    DiscoveryCandidate.status == "discovered",
                ).first()
                if existing:
                    continue
                prelim = score_preliminary_fit_cheap(name, context, use_llm=use_llm_preliminary)
                prelim_vert = _infer_prelim_vertical(name, context)
                d_score = compute_discovery_score_heuristic(context, prelim_vert)
                row = DiscoveryCandidate(
                    company_name=name,
                    context=context,
                    source_url=url,
                    source_query=q[:500],
                    prelim_vertical=prelim_vert or None,
                    preliminary_fit_score=prelim,
                    status="discovered",
                    discovery_rank=c.get("discovery_rank"),
                    discovery_score=d_score,
                )
                db.add(row)
                added += 1
        db.commit()
        logger.info(f"[Agent6 Stage1] Collected {added} new discovery candidates (no Apollo).")
    finally:
        db.close()
    return added


def stage2_sieve(threshold: Optional[int] = None) -> List[DiscoveryCandidate]:
    """Stage 2: Pure evaluation. No Company, no Apollo, no contacts. score_candidate → prelim_fit_score, scored_at; status scored | rejected. Single commit."""
    from scoring import score_candidate

    db = SessionLocal()
    thresh = threshold if threshold is not None else getattr(config, "NEWS_DISCOVERY_SIEVE_THRESHOLD", 80)
    now = datetime.now(timezone.utc)
    try:
        # Only score primary entities: include unresolved (entity_confidence is None) or passed (>= threshold)
        thresh_conf = getattr(config, "NEWS_DISCOVERY_ENTITY_CONFIDENCE_THRESHOLD", ENTITY_CONFIDENCE_THRESHOLD)
        candidates = (
            db.query(DiscoveryCandidate)
            .filter(
                DiscoveryCandidate.status.in_(["discovered", "pending"]),
                or_(DiscoveryCandidate.entity_confidence.is_(None), DiscoveryCandidate.entity_confidence >= thresh_conf),
            )
            .order_by(nulls_last(desc(DiscoveryCandidate.discovery_score)), nulls_last(asc(DiscoveryCandidate.discovery_rank)))
            .all()
        )
        scored_count = 0
        rejected_count = 0
        for cand in candidates:
            ctx = (cand.context or "") + " " + (cand.company_name or "")
            if SIEVE_REJECT_RE.search(ctx):
                cand.status = "rejected"
                cand.rejected_reason = "Revenue-role sieve: Ops/Support/Enablement in context"
                cand.scored_at = now
                rejected_count += 1
                continue
            score = score_candidate(
                company_name=cand.company_name or "",
                vertical=cand.prelim_vertical or "",
                context=cand.context or "",
            )
            cand.preliminary_fit_score = score
            cand.scored_at = now
            if score < thresh:
                cand.status = "rejected"
                cand.rejected_reason = f"Below threshold ({score} < {thresh})"
                rejected_count += 1
            else:
                cand.status = "scored"
                scored_count += 1
        db.commit()
        eligible = [c for c in candidates if c.status == "scored"]
        eligible.sort(key=lambda c: (-(c.discovery_score or 0), (c.discovery_rank or 999)))
        logger.info(f"[Agent6 Stage2] Sieve: {scored_count} scored (>= {thresh}), {rejected_count} rejected. Pure eval, no Apollo.")
        return eligible
    finally:
        db.close()


def _domain_from_org(o: Dict[str, Any]) -> Optional[str]:
    d = (o.get("primary_domain") or o.get("domain") or o.get("website_url") or "").strip()
    if not d:
        return None
    return d.replace("https://", "").replace("http://", "").split("/")[0].lower()


def stage3_invest(
    candidates: Optional[List[DiscoveryCandidate]] = None,
    max_new_per_run: Optional[int] = None,
    run_gtm_scan: bool = True,
    threshold: Optional[int] = None,
) -> int:
    """Stage 3: Apollo enrich only for given candidates (or top N from sieve). Promote to Company + signals."""
    from apollo_client import ApolloClient

    db = SessionLocal()
    apollo = ApolloClient()
    max_new = max_new_per_run or getattr(config, "NEWS_DISCOVERY_MAX_NEW_COMPANIES_PER_RUN", 20)
    thresh = threshold if threshold is not None else getattr(config, "NEWS_DISCOVERY_SIEVE_THRESHOLD", 80)
    use_llm = not getattr(config, "NEWS_DISCOVERY_DISABLE_LLM", False)
    promoted = 0

    if candidates is None or len(candidates) == 0:
        to_process = (
            db.query(DiscoveryCandidate)
            .filter(DiscoveryCandidate.status == "scored", DiscoveryCandidate.preliminary_fit_score >= thresh)
            .order_by(
                nulls_last(desc(DiscoveryCandidate.discovery_score)),
                nulls_last(asc(DiscoveryCandidate.discovery_rank)),
                DiscoveryCandidate.preliminary_fit_score.desc(),
            )
            .limit(max_new * 2)
            .all()
        )
    else:
        ids = [c.id for c in candidates if getattr(c, "id", None)]
        to_process = (
            db.query(DiscoveryCandidate)
            .filter(DiscoveryCandidate.id.in_(ids), DiscoveryCandidate.status == "scored")
            .order_by(
                nulls_last(desc(DiscoveryCandidate.discovery_score)),
                nulls_last(asc(DiscoveryCandidate.discovery_rank)),
                DiscoveryCandidate.preliminary_fit_score.desc(),
            )
            .all()
        ) if ids else []

    try:
        for dc in to_process[:max_new]:
            if promoted >= max_new:
                break
            name = (dc.canonical_company_name or dc.company_name or "").strip()
            context = dc.context or ""
            source_url = dc.source_url or ""
            if not name:
                continue
            existing_co = db.query(Company).filter(Company.name.ilike(name)).first()
            if existing_co:
                dc.status = "promoted"
                dc.promoted_at = datetime.now(timezone.utc)
                dc.promoted_company_id = existing_co.id
                dc.rejected_reason = "Already in companies"
                continue
            orgs = apollo.search_organizations(name)
            if not orgs:
                continue
            best = orgs[0]
            domain = _domain_from_org(best)
            canon_name = (best.get("name") or name).strip()
            emp = best.get("estimated_num_employees") or best.get("employee_count")
            industry = (best.get("industry") or best.get("primary_domain") or "").lower()
            if db.query(Company).filter(Company.name.ilike(canon_name)).first():
                dc.status = "rejected"
                dc.rejected_reason = "Apollo match already in companies"
                continue
            if use_llm:
                prompt = f"""Evaluate for Senior Enterprise Sales role fit (Payer/Healthcare/Fintech).
Company: {canon_name} | Domain: {domain or 'unknown'} | Context: {context[:300]}.
If this looks like a real company selling to healthcare payers, health plans, or fintech buyers, set include=true and fit_score 0-100. Otherwise include=false.
Return JSON: {{"include": bool, "fit_score": 0-100, "vertical": "string"}}"""
                try:
                    resp = call_llm(prompt, response_format="json")
                    res = parse_json_from_llm(resp) or {}
                except Exception:
                    res = {}
                if not res.get("include"):
                    dc.status = "rejected"
                    dc.rejected_reason = "LLM fit rejection"
                    continue
                vert = res.get("vertical", "other")
                fit = int(res.get("fit_score") or 0)
            else:
                vert = "other"
                if any(k in industry or k in canon_name.lower() for k in ["health", "payer", "medicare", "medicaid", "plan", "care"]):
                    vert = "healthcare_payer" if any(p in industry or p in canon_name.lower() for p in ["payer", "plan", "medicare", "medicaid"]) else "healthcare_general"
                elif any(k in industry or k in canon_name.lower() for k in ["fintech", "payment", "insurance"]):
                    vert = "fintech"
                fit = 50 if "health" in vert or "fintech" in vert else 30
            co = Company(
                id=str(uuid.uuid4()),
                name=canon_name,
                domain=domain,
                vertical=vert or "other",
                stage="",
                funding_total=None,
                employee_count=emp,
                hq_location=None,
                fit_score=fit,
                monitoring_status="active",
                raw_data={"discovery_source": "agent6_news", "context": context[:500], "source_url": source_url},
            )
            db.add(co)
            db.flush()
            sig = CompanySignal(
                company_id=co.id,
                signal_type="discovery",
                signal_date=datetime.now(timezone.utc),
                signal_text=f"Discovered via news: {context[:300]}",
                score=fit,
                source_url=source_url,
            )
            db.add(sig)
            if run_gtm_scan and domain and (emp or 0) >= 40:
                gtm_titles = getattr(config, "APOLLO_PRIMARY_GTM_TITLES", ["Chief Revenue Officer", "CRO", "VP Sales", "Head of Sales"])
                people = apollo.search_people(company_domain=domain, titles=gtm_titles[:5])
                has_cro = any(("cro" in (p.get("title") or "").lower()) or ("chief revenue" in (p.get("title") or "").lower()) for p in (people or []))
                has_head_sales = any("head of sales" in (p.get("title") or "").lower() for p in (people or []))
                if not has_cro and not has_head_sales:
                    gap = CompanySignal(
                        company_id=co.id,
                        signal_type="gtm_leadership_gap",
                        signal_date=datetime.now(timezone.utc),
                        signal_text=f"GTM gap: No CRO/Head of Sales found; ~{emp or '?'} employees",
                        score=75,
                        source_url=f"https://{domain}" if domain else source_url,
                    )
                    db.add(gap)
            dc.status = "promoted"
            dc.promoted_at = datetime.now(timezone.utc)
            dc.promoted_company_id = co.id
            promoted += 1
            logger.info(f"[Agent6 Stage3] Promoted: {co.name} ({co.vertical}, fit={co.fit_score})")
        db.commit()
        logger.info(f"[Agent6 Stage3] Promoted {promoted} companies (Apollo used only for these).")
    finally:
        db.close()
    return promoted


def clear_discovery_candidates() -> int:
    """Delete all rows from discovery_candidates. Returns count deleted. Use when table is polluted from earlier runs."""
    db = SessionLocal()
    try:
        n = db.query(DiscoveryCandidate).delete()
        db.commit()
        logger.info(f"[Agent6] Cleared {n} discovery candidates.")
        return n
    finally:
        db.close()


def run_discovery(
    max_new_per_run: Optional[int] = None,
    run_gtm_scan: bool = True,
    max_articles_per_query: Optional[int] = None,
    sieve_threshold: Optional[int] = None,
    stage: Optional[int] = None,
    clear: bool = False,
) -> None:
    """Run full pipeline Stage1 → Stage2 → Stage3, or a single stage if stage=1|2|3. If clear=True, wipe discovery_candidates first."""
    from database import init_db
    init_db()  # ensure discovery_candidates table exists
    if clear:
        clear_discovery_candidates()
    start = time.time()
    if stage == 1:
        stage1_collect(max_articles_per_query=max_articles_per_query)
    elif stage == 2:
        stage1_5_entity_resolution()
        stage2_sieve(threshold=sieve_threshold)
    elif stage == 3:
        stage3_invest(max_new_per_run=max_new_per_run, run_gtm_scan=run_gtm_scan, threshold=sieve_threshold)
    else:
        stage1_collect(max_articles_per_query=max_articles_per_query)
        stage1_5_entity_resolution()
        eligible = stage2_sieve(threshold=sieve_threshold)
        stage3_invest(candidates=eligible, max_new_per_run=max_new_per_run, run_gtm_scan=run_gtm_scan, threshold=sieve_threshold)
    logger.info(f"[Agent6] Done. Elapsed {time.time() - start:.1f}s")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="News-driven discovery (Agent 6) — staged Pull-to-Enrich")
    p.add_argument("--stage", type=int, choices=[1, 2, 3], default=None, help="Run only stage 1 (Collect), 2 (Sieve), or 3 (Invest)")
    p.add_argument("--max-new", type=int, default=None, help="Max new companies to promote in Stage 3")
    p.add_argument("--no-gtm-scan", action="store_true", help="Skip GTM leadership gap scan in Stage 3")
    p.add_argument("--max-articles", type=int, default=None, help="Max articles per topic in Stage 1")
    p.add_argument("--sieve-threshold", type=int, default=None, help="Min preliminary_fit for Stage 3 (default from config)")
    p.add_argument("--clear", action="store_true", help="Clear discovery_candidates table before running (use when polluted)")
    args = p.parse_args()
    run_discovery(
        max_new_per_run=args.max_new,
        run_gtm_scan=not args.no_gtm_scan,
        max_articles_per_query=args.max_articles,
        sieve_threshold=args.sieve_threshold,
        stage=args.stage,
        clear=args.clear,
    )
