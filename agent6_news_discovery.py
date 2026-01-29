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

# Load .env first (before any other imports that read env) so PERPLEXITY_API_KEY etc. are available
from pathlib import Path
import os
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)

import logging
import random
import re
import time
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote_plus, urlencode

import requests
import xml.etree.ElementTree as ET

import config
from database import SessionLocal
from models import Company, CompanySignal, DiscoveryCandidate
from sqlalchemy import asc, desc, nulls_last, or_
from utils import call_llm, parse_json_from_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# One-time env check so we see if PERPLEXITY_API_KEY is loaded at runtime (remove after debugging if desired)
_pplx = os.getenv("PERPLEXITY_API_KEY")
logger.info(f"[ENV] PERPLEXITY_API_KEY present: {bool(_pplx)}, value length: {len(_pplx or '')}")

# Sieve: reject if context contains these (Revenue Role ONLY)
SIEVE_REJECT_PATTERNS = [
    r"sales\s*ops", r"sales\s*operations", r"enablement", r"revops", r"revenue\s*operations",
    r"customer\s*success\s*manager", r"\bcsm\b", r"implementation\s*manager", r"implementation\s*consultant",
    r"support\s*specialist", r"sales\s*admin", r"operations\s*coordinator",
]
SIEVE_REJECT_RE = re.compile("|".join(f"({p})" for p in SIEVE_REJECT_PATTERNS), re.IGNORECASE)

# Discovery bias: only pass articles that match ≥1 high-value trigger (before LLM)
# Article text is lowercased for matching — include lowercase so we don't filter out valid sub-verticals
HIGH_VALUE_TRIGGERS = [
    "raised $", "Series A", "Series B", "Series C", "growth", "expanding", "launches",
    "health plan", "payer", "Medicare Advantage", "employer health", "PBM",
    "value-based care", "risk adjustment", "utilization management", "Chief Revenue", "CRO",
    "hires", "appoints", "raises",
    # Full healthtech infrastructure (RCM, physician, hospital, home health, ASC, telehealth, etc.)
    "RCM", "revenue cycle", "physician group", "medical practice", "practice management",
    "health system", "IDN", "home health", "hospice", "post-acute",
    "ambulatory surgery", "ASC", "telehealth", "digital health", "virtual care",
    "behavioral health", "mental health", "specialty pharmacy",
    "VP Sales", "sales leadership",
    # Lowercase / single-word variants (article text is lowercased)
    "rcm", "billing", "hospital", "idn", "lab", "pathology", "diagnostics", "asc",
]
# Suppress articles that look like services/research/hospital noise
DISCOVERY_NEGATIVE = [
    "consulting", "research firm", "hospital system", "clinic ", "clinical research",
    "contract research organization", "CRO study", "clinical trial",
]
MAX_PER_ARTICLE = 3  # cap companies extracted per article (or per batch when batched)

# 1. Define the Promotion Keywords at the top of the file
PROMOTION_KEYWORDS = [
    "funding", "raises", "raised", "expansion", "expanding", 
    "launch", "hires", "hired", "Series A", "Series B", "Series C", 
    "CRO", "VP Sales", "Chief Revenue", "partnership", "partner"
]


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


# Expanded query breadth: payer + full healthtech infrastructure (news/RSS)
DISCOVERY_QUERIES_EXPANDED = [
    # Payer / MA / value-based
    "health plan series OR funding",
    '"Medicare Advantage" expansion OR growth',
    'payer OR "health plan" "VP Sales" OR CRO OR "Chief Revenue"',
    '"value-based care" launch OR platform',
    '"risk adjustment" payer OR Medicare',
    '"Medicaid" managed care OR utilization',
    'employer health benefits OR "PBM"',
    '"payment integrity" OR "fraud detection" payer',
    '"utilization management" health plan',
    "payer technology OR insurtech series",
    '"Series B" healthcare OR healthtech',
    "health plan CRO hire OR appoints",
    "Medicare Advantage startup OR raises",
    "value-based care vendor OR platform",
    "risk adjustment technology OR solution",
    "payer analytics OR health plan data",
    "employer health benefits technology",
    "PBM technology OR pharmacy benefit",
    # RCM / physician / hospital / home health / ASC
    "RCM OR revenue cycle billing funding OR hire",
    "physician group OR medical practice practice management CRO OR funding",
    "hospital OR health system IDN CRO OR VP Sales OR expansion",
    "home health OR hospice post-acute funding OR sales leadership",
    "ambulatory surgery center ASC funding OR revenue",
    # Telehealth / behavioral / biotech / pharmacy / lab
    "telehealth OR digital health virtual care series OR funding",
    "behavioral health OR mental health addiction funding OR CRO",
    "biotech OR medical device diagnostics provider sales",
    "specialty pharmacy OR pharmacy benefit funding OR hire",
    "lab OR diagnostics pathology payer OR provider sales",
]

# X (Twitter) high-signal queries — payer + full healthtech infrastructure (20–30 for 500–5k raw/day)
X_QUERIES = [
    # Payer / MA / value-based (existing)
    'payer OR "Medicare Advantage" OR "health plan" OR PBM (funding OR raised OR series OR "CRO hire" OR "VP Sales" OR expansion OR launch) lang:en -is:retweet',
    '"value-based care" OR "risk adjustment" OR "utilization management" ("funding" OR "hiring" OR CRO OR "Chief Revenue") lang:en',
    '"Medicaid" OR "Medicare" "payer" OR "health plan" ("new hire" OR appoint OR "leadership change") lang:en',
    '"Series A" OR "Series B" (payer OR "health plan" OR healthtech OR insurtech) lang:en',
    '"payment integrity" OR "fraud detection" payer OR "health plan" lang:en',
    '"Medicare Advantage" startup OR raises OR expansion lang:en',
    'health plan "CRO" OR "VP Sales" OR "Chief Revenue" hire OR appoints lang:en',
    '"risk adjustment" payer OR Medicare funding OR series lang:en',
    '"utilization management" health plan OR payer launch OR platform lang:en',
    '"employer health" OR self-funded benefits (tech OR platform OR funding) lang:en',
    # RCM / revenue cycle
    '"RCM" OR "revenue cycle" OR "billing" (payer OR provider) (funding OR hire OR CRO OR "VP Sales") lang:en',
    # Physician groups / practices
    '"physician group" OR "medical practice" OR "practice management" (funding OR hire OR CRO OR expansion) lang:en',
    # Hospitals / health systems
    '"hospital" OR "health system" OR "IDN" ("CRO" OR "VP Sales" OR expansion OR funding) lang:en',
    # Home health / hospice / post-acute
    '"home health" OR hospice OR "post-acute" (funding OR "sales leadership" OR CRO OR hire) lang:en',
    # Ambulatory surgery centers
    '"ambulatory surgery" OR ASC (funding OR revenue OR CRO OR "VP Sales") lang:en',
    # Digital health / telehealth
    'telehealth OR "digital health" OR "virtual care" (series OR funding OR hire OR CRO) lang:en',
    # Behavioral / mental health
    '"behavioral health" OR "mental health" OR "addiction treatment" OR therapy (funding OR CRO OR "VP Sales") lang:en',
    # Biotech / med device (provider-facing)
    'biotech OR "medical device" OR diagnostics ("provider" OR "hospital" OR sales OR revenue) lang:en',
    # Specialty pharmacy / PBM-adjacent
    '"specialty pharmacy" OR "pharmacy benefit" (funding OR hire OR CRO) lang:en',
    # Lab / diagnostics
    '"lab" OR "diagnostics" OR pathology (payer OR provider OR sales OR CRO) lang:en',
    # Additional variants for breadth (different keyword combos)
    '"RCM" OR "revenue cycle" OR "billing" payer OR provider (funding OR hire OR CRO OR "VP Sales") lang:en',
    '"physician group" OR "medical practice" OR "practice management" (funding OR hire OR CRO OR expansion) lang:en',
    '"hospital" OR "health system" OR "IDN" "CRO" OR "VP Sales" OR funding lang:en',
    '"home health" OR hospice OR "post-acute" funding OR hire OR CRO lang:en',
    '"ambulatory surgery" OR ASC (funding OR sales OR revenue) lang:en',
    'telehealth OR "digital health" OR "virtual care" series OR funding OR "sales leadership" lang:en',
    '"behavioral health" OR "mental health" OR "addiction treatment" funding OR CRO lang:en',
    'biotech OR "medical device" OR diagnostics provider OR hospital sales OR revenue lang:en',
    '"specialty pharmacy" OR "pharmacy benefit" funding OR hire OR CRO lang:en',
    '"lab" OR "diagnostics" OR pathology payer OR provider CRO OR funding lang:en',
]


# --- Multi-provider news API (keys from .env only) ---

# Provider order: NewsData (higher free limits), GNews, MediaStack. Shuffled per run to balance load. NewsAPI optional fallback.
def _news_providers() -> List[Dict[str, Any]]:
    raw = [
        {"name": "newsdata1", "key": os.getenv("NEWSDATA_API_KEY1"), "type": "newsdata", "endpoint": "https://newsdata.io/api/1/latest"},
        {"name": "newsdata2", "key": os.getenv("NEWSDATA_API_KEY2"), "type": "newsdata", "endpoint": "https://newsdata.io/api/1/latest"},
        {"name": "gnews1", "key": os.getenv("GNEWS_API_KEY1"), "type": "gnews", "endpoint": "https://gnews.io/api/v4/search"},
        {"name": "gnews2", "key": os.getenv("GNEWS_API_KEY2"), "type": "gnews", "endpoint": "https://gnews.io/api/v4/search"},
        {"name": "mediastack1", "key": os.getenv("MEDIASTACK_API_KEY1"), "type": "mediastack", "endpoint": "http://api.mediastack.com/v1/news"},
    ]
    newsapi_key = os.getenv("NEWS_API_KEY")
    if newsapi_key and "your_" not in str(newsapi_key):
        raw.append({"name": "newsapi", "key": newsapi_key, "type": "newsapi", "endpoint": "https://newsapi.org/v2/everything"})
    with_keys = [p for p in raw if p.get("key") and "your_" not in str(p.get("key", ""))]
    random.shuffle(with_keys)
    return with_keys


def _normalize_article(art: Dict[str, Any], source_name: str) -> Dict[str, Any]:
    """Common format: title, description, url, snippet, published_at, source."""
    title = (art.get("title") or art.get("headline") or "").strip()
    desc = (art.get("description") or art.get("content") or art.get("snippet") or "").strip()
    url = (art.get("url") or art.get("link") or art.get("web_url") or "").strip()
    pub = art.get("published_at") or art.get("publishedAt") or art.get("pubDate") or art.get("published_at")
    return {
        "title": title,
        "description": desc,
        "snippet": desc,
        "url": url,
        "published_at": pub,
        "source": source_name,
    }


def _fetch_newsdata(
    provider: Dict[str, Any], query: str, page_size: int, page_token: Optional[str] = None
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Optional[str]]:
    """NewsData.io: apikey, q, language=en, size=10. No country (free tier 422). Returns (articles, error, next_page_token)."""
    # Free tier: size must be 10; country=us often causes 422 — omit country entirely
    params = {
        "apikey": provider["key"],
        "q": query,
        "language": "en",
        "size": 10,  # hard set for free tier; no min(page_size, 10)
    }
    if page_token:
        params["page"] = page_token
    try:
        url = provider["endpoint"]
        params_safe = {k: "***" if k == "apikey" else v for k, v in params.items()}
        logger.info(f"[Agent6] NewsData request URL: {url}?{urlencode(params_safe)}")
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            return None, "rate limit (429)", None
        if resp.status_code == 401:
            return None, "invalid key (401)", None
        if resp.status_code != 200:
            body = resp.text or ""
            try:
                body_json = resp.json()
                body = str(body_json)  # full body for 422 debugging
            except Exception:
                body = (body or "")[:1000]
            logger.warning(f"[Agent6] NewsData non-200 response: {resp.status_code} body={body!r}")
            return None, f"HTTP {resp.status_code}", None
        data = resp.json()
        results = data.get("results") or data.get("articles") or []
        out = [_normalize_article(r, provider["name"]) for r in results if (r.get("title") or r.get("link"))]
        next_token = data.get("nextPage") if isinstance(data.get("nextPage"), str) else None
        return out[:page_size], None, next_token
    except requests.exceptions.Timeout:
        return None, "timeout", None
    except Exception as e:
        logger.debug(f"[Agent6] NewsData request error: {e}")
        return None, str(e), None


def _fetch_gnews(provider: Dict[str, Any], query: str, page_size: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """GNews.io v4: apikey, q, lang=en, max."""
    params = {"apikey": provider["key"], "q": query, "lang": "en", "max": min(page_size, 50)}
    try:
        resp = requests.get(provider["endpoint"], params=params, timeout=15)
        if resp.status_code == 429:
            return None, "rate limit (429)"
        if resp.status_code == 401:
            return None, "invalid key (401)"
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        data = resp.json()
        results = data.get("articles") or data.get("results") or []
        out = [_normalize_article(r, provider["name"]) for r in results if (r.get("title") or r.get("url"))]
        return out[:page_size], None
    except requests.exceptions.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def _fetch_mediastack(provider: Dict[str, Any], query: str, page_size: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """MediaStack: access_key, keywords, limit."""
    params = {"access_key": provider["key"], "keywords": query, "limit": min(page_size, 50), "languages": "en"}
    try:
        resp = requests.get(provider["endpoint"], params=params, timeout=15)
        if resp.status_code == 429:
            return None, "rate limit (429)"
        if resp.status_code == 401:
            return None, "invalid key (401)"
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        data = resp.json()
        results = data.get("data") or []
        out = [_normalize_article(r, provider["name"]) for r in results if (r.get("title") or r.get("url"))]
        return out[:page_size], None
    except requests.exceptions.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def _fetch_newsapi(provider: Dict[str, Any], query: str, page_size: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """NewsAPI.org: apiKey, q, sortBy, pageSize."""
    params = {"q": query, "sortBy": "publishedAt", "pageSize": min(page_size, 100), "apiKey": provider["key"]}
    try:
        resp = requests.get(provider["endpoint"], params=params, timeout=15)
        if resp.status_code == 429:
            return None, "rate limit (429)"
        if resp.status_code == 401:
            return None, "invalid key (401)"
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        data = resp.json()
        results = data.get("articles") or []
        out = [_normalize_article(r, provider["name"]) for r in results if (r.get("title") or r.get("url"))]
        return out[:page_size], None
    except requests.exceptions.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


_FETCH_BY_TYPE = {"newsdata": _fetch_newsdata, "gnews": _fetch_gnews, "mediastack": _fetch_mediastack, "newsapi": _fetch_newsapi}


def fetch_news_by_topic(
    query: str, page_size: int = 10, page_token: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Try providers until one returns articles. Returns (articles, next_page_token). NewsData supports nextPage for pagination."""
    providers = _news_providers()
    if not providers:
        logger.warning("[Agent6] No news API keys found (NEWSDATA_API_KEY1/2, GNEWS_API_KEY1/2, MEDIASTACK_API_KEY1, or NEWS_API_KEY). Skipping API fetch.")
        return [], None
    page_size = min(max(1, page_size), 50)
    # When requesting next page, only NewsData providers support it
    if page_token:
        providers = [p for p in providers if (p.get("type") or "newsdata") == "newsdata"]
        if not providers:
            return [], None
    for i, provider in enumerate(providers):
        if i > 0:
            time.sleep(1 + (i % 2))  # 1–2 s between attempts
        ptype = provider.get("type") or "newsdata"
        fetcher = _FETCH_BY_TYPE.get(ptype, _fetch_newsdata)
        collected: List[Dict[str, Any]] = []
        next_tok: Optional[str] = page_token
        max_pages = 5 if ptype == "newsdata" else 1
        for _ in range(max_pages):
            if ptype == "newsdata":
                articles, err, next_tok = _fetch_newsdata(provider, query, page_size, next_tok)
            else:
                articles, err = fetcher(provider, query, page_size)
                next_tok = None
            if err:
                logger.warning(f"[Agent6] {provider['name']} failed: {err}. Trying next provider.")
                break
            if articles:
                collected.extend(articles)
            if not next_tok:
                break
            time.sleep(1)
        if collected:
            logger.info(f"[Agent6] Fetched {len(collected)} articles from {provider['name']} for query (max {page_size}).")
            return collected, next_tok
    logger.warning("[Agent6] All news providers failed for this query.")
    return [], None


def fetch_x_signals(query: str, count: int = 200, max_pages: int = 5) -> List[Dict[str, Any]]:
    """Fetch X (Twitter) posts from TwitterAPI.io advanced_search. TWITTERAPI_IO_KEY in .env.
    Endpoint: https://api.twitterapi.io/twitter/tweet/advanced_search
    Header: x-api-key. Params: query, queryType=Latest, count (API cap 100), cursor for pagination.
    Response: json["tweets"] with text, id, url, createdAt, author, public_metrics; next_cursor, has_next_page.
    """
    key = os.getenv("TWITTERAPI_IO_KEY")
    if not key or "your_" in str(key):
        logger.info("[Agent6] Skipping X fetch (no TWITTERAPI_IO_KEY or placeholder).")
        return []
    # Debug: confirm key is loaded (masked)
    key_str = str(key).strip()
    if len(key_str) > 14:
        logger.info(f"[Agent6] [X] Using key: {key_str[:10]}...{key_str[-4:]}")
    else:
        logger.info(f"[Agent6] [X] Using key: (len={len(key_str)})")
    url = "https://api.twitterapi.io/twitter/tweet/advanced_search"
    headers = {"x-api-key": key}
    all_tweets: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    per_page = min(max(1, count // max_pages), 100)  # API cap 100
    try:
        for page in range(1, max_pages + 1):
            params = {"query": query, "queryType": "Latest", "count": per_page}
            if next_cursor:
                params["cursor"] = next_cursor
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"[Agent6] TwitterAPI.io {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            tweets = data.get("tweets", [])
            all_tweets.extend(tweets)
            next_cursor = data.get("next_cursor") or data.get("nextCursor")
            has_next = data.get("has_next_page", False)
            if not has_next or not next_cursor or len(tweets) == 0:
                break
            time.sleep(10)  # 10s between pages to avoid rate limit (429)
        logger.info(f"[Agent6] Fetched {len(all_tweets)} X posts from TwitterAPI.io for query '{query[:50]}...'")
    except requests.exceptions.Timeout:
        logger.warning("[Agent6] TwitterAPI.io request timeout.")
    except Exception as e:
        logger.warning(f"[Agent6] TwitterAPI.io error: {e}")
    # Normalize to common shape: text, created_at, id, url, author, source, raw
    out = []
    for t in all_tweets:
        author_obj = t.get("author") or {}
        author = author_obj.get("userName") or author_obj.get("username") or author_obj.get("screen_name") or ""
        tid = t.get("id")
        out.append({
            "text": t.get("text") or t.get("full_text") or "",
            "created_at": t.get("createdAt") or t.get("created_at"),
            "id": tid,
            "url": t.get("url") or (f"https://x.com/i/web/status/{tid}" if tid else ""),
            "author": author,
            "source": "x_twitter",
            "raw": t,
        })
    return out


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

# Perplexity models: try in order until one works (docs: https://docs.perplexity.ai/getting-started/models)
PERPLEXITY_ENTITY_MODELS = [
    "sonar", "sonar-pro", "sonar-reasoning-pro",
    "llama-3.1-sonar-small-128k-online",
    "llama-3.1-sonar-large-128k-online"
]


def _call_perplexity_entity_resolution(prompt: str) -> Optional[str]:
    """Call Perplexity API for entity resolution. Returns response content or None on failure (then caller uses MiniMax)."""
    key = os.getenv("PERPLEXITY_API_KEY")
    if not key or "your_" in str(key):
        return None
    url = "https://api.perplexity.ai/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    messages = [{"role": "user", "content": prompt}]
    for model in PERPLEXITY_ENTITY_MODELS:
        data = {
            "model": model,
            "messages": messages,
            "max_tokens": 300,
            "temperature": 0.3,
        }
        logger.info(f"[Perplexity] Trying model: {model}")
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=60)
            if resp.status_code == 200:
                logger.info(f"[Perplexity] Success with model: {model}")
                resp_data = resp.json()
                content = (resp_data.get("choices") or [{}])[0].get("message") or {}
                return (content.get("content") or "").strip()
            err_msg = (resp.text or "")[:200]
            logger.warning(f"[Perplexity] Model {model} failed: {resp.status_code} {err_msg}")
        except requests.exceptions.Timeout:
            logger.warning(f"[Perplexity] Model {model} failed: timeout")
        except Exception as e:
            logger.warning(f"[Perplexity] Model {model} failed: {e}")
    logger.error("[Perplexity] All models failed; falling back to MiniMax")
    return None


def _call_deepseek_entity_resolution(prompt: str) -> Optional[str]:
    """Call local DeepSeek-R1 32B via Ollama OpenAI-compatible endpoint."""
    # Note: Use your exact model name from 'ollama list'
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-r1:32b")
    base_url = os.getenv("DEEPSEEK_API_BASE", "http://localhost:11434/v1")

    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "stream": False,
            "think": False, # The Ollama specific toggle
            "options": {
                "stop": ["<think>", "</think>"] # The hard stop sequence
            }
        }
        resp = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            timeout=90  # Local 32B can take time even without thinking
        )
        if resp.status_code == 200:
            raw_content = resp.json()['choices'][0]['message']['content'] or ""
            # R1 sometimes ignores stop sequences in JSON mode; strip <think>...</think>
            cleaned_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()
            return cleaned_content or raw_content
        else:
            logger.warning(f"[DeepSeek] Local call failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"[DeepSeek] Error: {e}")
    return None


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
    """Ranked extraction: up to {cap} companies most likely GTM-relevant, best first. Capped by max_per_batch."""
    if not articles:
        return []
    cap = max_per_batch if max_per_batch is not None else min(15, MAX_PER_ARTICLE * max(1, len(articles)))
    batch = []
    for a in articles[:10]:
        t = (a.get("title") or "").strip()
        s = (a.get("description") or a.get("snippet") or "").strip()[:300]
        batch.append(f"T: {t}\nS: {s}")
    block = "\n\n".join(batch)
    
    prompt = f"""Identify all commercial companies mentioned in the text below.
Exclude government bodies, generic terms (like 'startups'), and locations.
Return ONLY a valid JSON list of strings.
Example: ["Stripe", "Google", "Anthropic"]

Text:
{block}"""

    out = []
    seen = set()
    url = articles[0].get("url") or ""
    title = (articles[0].get("title") or "")[:200]

    # 1. Try DeepSeek (Local) first
    if os.getenv("DEEPSEEK_API_BASE"):
        try:
            logger.debug("[Stage 1] Using DeepSeek for name extraction...")
            content = _call_deepseek_entity_resolution(prompt)
            if content:
                names = parse_json_from_llm(content) or []
                if isinstance(names, list):
                    for rank, name in enumerate(names[:cap], start=1):
                        name = (name or "").strip()
                        if 3 <= len(name) <= 60 and name not in seen:
                            seen.add(name)
                            out.append({"company_name": name, "context": title, "source_url": url, "discovery_rank": rank})
                    if out:
                        return out
        except Exception as e:
            logger.warning(f"[Stage 1] DeepSeek extraction failed: {e}. Falling back to MiniMax.")

    # 2. Fallback to MiniMax (call_llm)
    try:
        resp = call_llm(prompt, response_format="json", temperature=0.1)
        names = parse_json_from_llm(resp) or []
        if isinstance(names, list):
            for rank, name in enumerate(names[:cap], start=1):
                name = (name or "").strip()
                if 3 <= len(name) <= 60 and name not in seen:
                    seen.add(name)
                    out.append({"company_name": name, "context": title, "source_url": url, "discovery_rank": rank})
    except Exception as e:
        logger.error(f"[Stage 1] LLM extraction failed: {e}")
    
    return out


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


ENTITY_CONFIDENCE_THRESHOLD = 60  # 0–100; below this → reject in Stage 1.5 (relaxed from 70 to keep more candidates)

# Second Chance: if LLM marks as "secondary" but context has these, promote to candidate (safety net)
SECOND_CHANCE_PROMOTION_KEYWORDS = [
    "funding", "raises", "raised", "expansion", "expanding", "launch", "launches", "hires", "hired",
    "Series A", "Series B", "Series C", "CRO", "VP Sales", "Chief Revenue", "partnership", "partner",
]


def _normalize_name(s: str) -> str:
    """Strip leading 'N. ' list prefixes for matching."""
    if not s:
        return ""
    return re.sub(r"^\d+\.\s*", "", (s or "").strip()).strip()





def resolve_entity_llm(
    article_context: str,
    company_names: List[str],
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM entity resolution: who is the single primary commercial actor? Returns {primary_company: {name, confidence}, secondary_mentions, reasoning}.
    provider: 'deepseek' | 'perplexity' | 'minimax' | None/'auto' (auto = DeepSeek → Perplexity → MiniMax)."""
    if not company_names:
        return {"primary_company": {"name": "", "confidence": 0}, "secondary_mentions": [], "reasoning": ""}
    names_block = "\n".join(f"- {n}" for n in company_names[:15])
    prompt = f"""You are a GTM scout for a healthtech firm. Identify all 'Primary Commercial Actors' in the snippet. A company is primary if it is hiring, raising funds, or launching products. If a startup is partnering with a payer (CVS, United), **both** are primary. Do not categorize a company as 'secondary' unless it is a competitor used for comparison. Aim for high recall over precision.

Given the article and extracted names below, choose the single most relevant primary company (when multiple are actors, pick the one most central to the story). List as secondary_mentions only companies that are purely contextual or competitors used for comparison.

Article/snippet:
{article_context[:800]}

Extracted names:
{names_block}

Return JSON only with:
- primary_company: {{"name": "<exact company name>", "confidence": 0.0–1.0}}
- secondary_mentions: ["name1", "name2"]
- reasoning: one sentence
"""
    out = None
    use_auto = provider in (None, "", "auto")
    # Explicit provider: use only that one
    if provider == "deepseek":
        resp_content = _call_deepseek_entity_resolution(prompt)
        if resp_content:
            out = parse_json_from_llm(resp_content)
    elif provider == "perplexity":
        resp_content = _call_perplexity_entity_resolution(prompt)
        if resp_content:
            out = parse_json_from_llm(resp_content)
    elif provider == "minimax":
        try:
            resp = call_llm(prompt, response_format="json", temperature=0.1)
            out = parse_json_from_llm(resp) or {}
        except Exception as e:
            logger.warning(f"Entity resolution (MiniMax) failed: {e}")
            first = (company_names[0] or "").strip()
            return {"primary_company": {"name": first, "confidence": 0.5}, "secondary_mentions": company_names[1:], "reasoning": "fallback"}
    else:
        # Auto: DeepSeek → Perplexity → MiniMax
        if (os.getenv("DEEPSEEK_API_BASE") or "").strip():
            resp_content = _call_deepseek_entity_resolution(prompt)
            if resp_content:
                out = parse_json_from_llm(resp_content)
        if out is None:
            _key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
            if len(_key) > 10 and "your_" not in _key.lower():
                resp_content = _call_perplexity_entity_resolution(prompt)
                if resp_content:
                    out = parse_json_from_llm(resp_content)
        if out is None:
            try:
                resp = call_llm(prompt, response_format="json", temperature=0.1)
                out = parse_json_from_llm(resp) or {}
            except Exception as e:
                logger.warning(f"Entity resolution LLM (fallback) failed: {e}")
                first = (company_names[0] or "").strip()
                return {"primary_company": {"name": first, "confidence": 0.5}, "secondary_mentions": company_names[1:], "reasoning": "fallback"}
    if not out:
        first = (company_names[0] or "").strip()
        return {"primary_company": {"name": first, "confidence": 0.5}, "secondary_mentions": company_names[1:], "reasoning": "fallback"}
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


def stage1_5_entity_resolution(
    confidence_threshold: int = ENTITY_CONFIDENCE_THRESHOLD,
    entity_resolution_provider: Optional[str] = None,
) -> int:
    """Stage 1.5: Entity cleansing. Group by source_url, resolve primary actor per article; reject secondaries and low-confidence. Sets canonical_company_name, entity_confidence.
    entity_resolution_provider: 'auto' | 'deepseek' | 'perplexity' | 'minimax' (from --entity-resolution flag)."""
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
        # Log which provider will be used (flag overrides auto priority)
        provider = (entity_resolution_provider or "auto").strip().lower() or "auto"
        _deepseek_base = (os.getenv("DEEPSEEK_API_BASE") or "").strip()
        _deepseek_model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-r1").strip()
        _pplx_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
        _pplx_valid = len(_pplx_key) > 10 and "your_" not in _pplx_key.lower()
        if provider == "deepseek":
            logger.info(f"[Agent6] Using local DeepSeek for entity resolution (model: {_deepseek_model}, --entity-resolution=deepseek).")
        elif provider == "perplexity":
            logger.info("[Agent6] Using Perplexity for entity resolution (--entity-resolution=perplexity).")
        elif provider == "minimax":
            logger.info("[Agent6] Using MiniMax for entity resolution (--entity-resolution=minimax).")
        elif _deepseek_base:
            logger.info(f"[Agent6] Using local DeepSeek for entity resolution (model: {_deepseek_model}).")
        elif _pplx_valid:
            logger.info("[Agent6] Using Perplexity for entity resolution.")
        else:
            logger.warning("[Agent6] DEEPSEEK_API_BASE and PERPLEXITY_API_KEY not set; falling back to MiniMax.")
        by_url: Dict[str, List[DiscoveryCandidate]] = {}
        for r in rows:
            url = (r.source_url or "").strip() or "__none__"
            by_url.setdefault(url, []).append(r)
        rejected_low_conf = 0
        rejected_secondary = 0
        second_chance_promoted = 0
        passed = 0
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
                
                # Check primary matching (including partial match if primary_norm is significant)
                is_primary = (name_norm == primary_norm) or (primary_norm and primary_norm in name_norm and len(primary_norm) >= 4)
                
                if is_primary:
                    r.entity_confidence = conf_100
                    if conf_100 < confidence_threshold:
                        r.status = "rejected"
                        r.rejected_reason = f"Entity confidence {conf_100} < {confidence_threshold}"
                        rejected_low_conf += 1
                    else:
                        passed += 1
                else: 
                     # Secondary logic: User's "Second Chance"
                     # If marked as secondary but has PROMOTION_KEYWORDS in context -> promote
                     is_secondary = True # It failed is_primary check
                     has_signals = any(kw.lower() in (r.context or "").lower() for kw in PROMOTION_KEYWORDS)
                     
                     if has_signals:
                         logger.info(f"[Antigravity] Second Chance Promotion: {r.company_name} due to keyword match.")
                         r.entity_confidence = 100
                         r.status = "passed"
                         second_chance_promoted += 1
                     else:
                         r.status = "rejected_secondary"
                         r.rejected_reason = "Secondary mention / not primary commercial actor" 
                         rejected_secondary += 1
                updated += 1
        db.commit()
        logger.info(
            f"[Agent6 Stage1.5] Entity resolution done; {updated} processed → {passed} passed (conf>={confidence_threshold}), "
            f"{second_chance_promoted} second-chance promoted, {rejected_low_conf} low-confidence, {rejected_secondary} secondary."
        )
    finally:
        db.close()
    return updated


def stage1_collect(
    max_articles_per_query: Optional[int] = None,
    use_llm_extraction: bool = True,
    use_llm_preliminary: bool = False,
    x_only: bool = False,
) -> int:
    """Stage 1: Fetch news (expanded queries + total cap + up to 5 pages per query), extract names, cheap prelim. Write-through: every extracted candidate persisted as status='discovered'. No Apollo. If x_only=True, skip news/RSS and fetch only X (TwitterAPI.io)."""
    db = SessionLocal()
    max_total = max_articles_per_query if max_articles_per_query is not None else 2000
    queries = DISCOVERY_QUERIES_EXPANDED  # force 18+ queries for volume
    use_llm = use_llm_extraction and not getattr(config, "NEWS_DISCOVERY_DISABLE_LLM", False)
    added = 0
    try:
        # Gather articles: news + RSS first (unless x_only), then X (TwitterAPI.io). Dedupe by URL across all sources.
        all_articles: List[Dict[str, Any]] = []
        seen_urls: set = set()
        # --- News APIs + RSS (skip when --x-only for quick X-only test) ---
        if x_only:
            logger.info("[Agent6] X-only mode: skipping news/RSS; fetching X (TwitterAPI.io) only.")
        if not x_only:
            for q in queries:
                if len(all_articles) >= max_total:
                    break
                logger.info(f"[Agent6] Fetching query: {q[:60]}...")
                next_token: Optional[str] = None
                for page in range(1, 6):  # up to 5 pages per query
                    arts_news, next_token = fetch_news_by_topic(q, page_size=50, page_token=next_token)
                    for a in arts_news or []:
                        if "url" not in a and "link" in a:
                            a["url"] = a["link"]
                        if "description" not in a and "snippet" in a:
                            a["description"] = a["snippet"]
                        url = (a.get("url") or a.get("link") or "").strip()
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_articles.append({**a, "source_query": q[:500]})
                        if len(all_articles) >= max_total:
                            break
                    if not next_token:
                        break
                    time.sleep(2)  # polite delay between pages
                    if len(all_articles) >= max_total:
                        break
                # RSS once per query
                arts_rss = fetch_google_news_rss_by_query(q, max_items=30)
                for a in arts_rss or []:
                    if "url" not in a and "link" in a:
                        a["url"] = a["link"]
                    if "description" not in a and "snippet" in a:
                        a["description"] = a["snippet"]
                    url = (a.get("url") or a.get("link") or "").strip()
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_articles.append({**a, "source_query": q[:500]})
                    if len(all_articles) >= max_total:
                        break
                if len(all_articles) >= max_total:
                    break
        # --- X (Twitter) via TwitterAPI.io: after news/RSS, before trigger filter ---
        if os.getenv("TWITTERAPI_IO_KEY") and "your_" not in str(os.getenv("TWITTERAPI_IO_KEY", "")):
            x_total = 0
            total_x_added = 0
            for q in X_QUERIES:
                if len(all_articles) >= max_total:
                    break
                logger.info(f"[Agent6] Fetching X query: {q[:55]}...")
                x_posts = fetch_x_signals(q, count=200, max_pages=5)
                x_articles: List[Dict[str, Any]] = []
                for post in x_posts:
                    url = post.get("url") or ""
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        text = (post.get("text") or "").strip()
                        x_articles.append({
                            "title": text[:100],
                            "description": text,
                            "snippet": text,
                            "url": url,
                            "published_at": post.get("created_at"),
                            "source": "x_twitter",
                            "source_query": q[:500],
                            "raw_post": post,
                        })
                all_articles.extend(x_articles)
                total_x_added += len(x_articles)
                x_total += len(x_posts)
                time.sleep(10)  # 10s between X queries to avoid rate limit (429)
            logger.info(f"[Agent6] Fetched {x_total} X posts total (added {total_x_added} unique articles).")
        else:
            logger.info("[Agent6] Skipping X fetch (no TWITTERAPI_IO_KEY or placeholder).")
        logger.info(f"[Agent6] Gathered {len(all_articles)} raw articles (cap {max_total}).")
        if not all_articles:
            return 0
        url_to_query = {(a.get("url") or a.get("link") or "").strip(): a.get("source_query", "") for a in all_articles}
        articles = filter_articles_by_triggers(all_articles)
        logger.info(f"[Agent6] After trigger filter: {len(articles)} articles.")
        # Extract in chunks to avoid huge LLM payloads
        chunk_size = 20
        all_candidates: List[Dict[str, Any]] = []
        for i in range(0, len(articles), chunk_size):
            chunk = articles[i : i + chunk_size]
            cap = min(15, MAX_PER_ARTICLE * max(1, len(chunk)))
            candidates = (
                extract_company_names_llm(chunk, max_per_batch=cap)
                if use_llm
                else extract_company_names_heuristic(chunk, max_per_batch=cap)
            )
            for c in candidates:
                c["source_query"] = url_to_query.get(c.get("source_url") or "", "")
            all_candidates.extend(candidates)
        for c in all_candidates:
            name = (c.get("company_name") or "").strip()
            context = c.get("context") or ""
            url = c.get("source_url") or ""
            q = c.get("source_query") or ""
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
        logger.info(f"[Agent6 Stage1] Collected {added} new discovery candidates from {len(articles)} articles (no Apollo).")
    finally:
        db.close()
    return added


def stage2_sieve(threshold: Optional[int] = None) -> List[DiscoveryCandidate]:
    """Stage 2: Pure evaluation. No Company, no Apollo, no contacts. score_candidate → prelim_fit_score, scored_at; status scored | rejected. Single commit."""
    from scoring import score_candidate

    db = SessionLocal()
    thresh = threshold if threshold is not None else getattr(config, "NEWS_DISCOVERY_SIEVE_THRESHOLD", 55)
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
                source_url=cand.source_url,
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
    thresh = threshold if threshold is not None else getattr(config, "NEWS_DISCOVERY_SIEVE_THRESHOLD", 55)
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
                logger.info(f"[Agent6 Stage3] Skipped (already in companies): {name} (fit={dc.preliminary_fit_score})")
                continue
            orgs = apollo.search_organizations(name)
            if not orgs:
                logger.info(f"[Agent6 Stage3] Rejected promotion: {name} (fit={dc.preliminary_fit_score}, reason: Apollo no match)")
                continue
            best = orgs[0]
            domain = _domain_from_org(best)
            canon_name = (best.get("name") or name).strip()
            emp = best.get("estimated_num_employees") or best.get("employee_count")
            industry = (best.get("industry") or best.get("primary_domain") or "").lower()
            if db.query(Company).filter(Company.name.ilike(canon_name)).first():
                dc.status = "rejected"
                dc.rejected_reason = "Apollo match already in companies"
                logger.info(f"[Agent6 Stage3] Rejected promotion: {name} -> {canon_name} (reason: Apollo match already in companies)")
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
                    logger.info(f"[Agent6 Stage3] Rejected promotion: {canon_name} (fit={dc.preliminary_fit_score}, reason: LLM fit rejection)")
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
            ctx_snippet = (context or "")[:100].replace("\n", " ")
            logger.info(f"[Agent6 Stage3] Promoted: {co.name} (fit={co.fit_score}, vertical={co.vertical}, reason: {ctx_snippet!r})")
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
    x_only: bool = False,
    entity_resolution_provider: Optional[str] = None,
) -> None:
    """Run full pipeline Stage1 → Stage2 → Stage3, or a single stage if stage=1|2|3. If clear=True, wipe discovery_candidates first. If x_only=True, Stage 1 fetches only X. entity_resolution_provider: 'auto' | 'deepseek' | 'perplexity' | 'minimax' (from --entity-resolution)."""
    from database import init_db
    init_db()  # ensure discovery_candidates table exists
    if clear:
        clear_discovery_candidates()
    start = time.time()
    if stage == 1:
        stage1_collect(max_articles_per_query=max_articles_per_query, x_only=x_only)
    elif stage == 2:
        stage1_5_entity_resolution(entity_resolution_provider=entity_resolution_provider)
        stage2_sieve(threshold=sieve_threshold)
    elif stage == 3:
        stage3_invest(max_new_per_run=max_new_per_run, run_gtm_scan=run_gtm_scan, threshold=sieve_threshold)
    else:
        stage1_collect(max_articles_per_query=max_articles_per_query, x_only=x_only)
        stage1_5_entity_resolution(entity_resolution_provider=entity_resolution_provider)
        eligible = stage2_sieve(threshold=sieve_threshold)
        stage3_invest(candidates=eligible, max_new_per_run=max_new_per_run, run_gtm_scan=run_gtm_scan, threshold=sieve_threshold)
    logger.info(f"[Agent6] Done. Elapsed {time.time() - start:.1f}s")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="News-driven discovery (Agent 6) — staged Pull-to-Enrich")
    p.add_argument("--stage", type=int, choices=[1, 2, 3], default=None, help="Run only stage 1 (Collect), 2 (Sieve), or 3 (Invest)")
    p.add_argument("--max-new", type=int, default=None, help="Max new companies to promote in Stage 3")
    p.add_argument("--no-gtm-scan", action="store_true", help="Skip GTM leadership gap scan in Stage 3")
    p.add_argument("--max-articles", type=int, default=None, help="Max raw articles to gather per cycle (default 2000)")
    p.add_argument("--sieve-threshold", type=int, default=None, help="Min preliminary_fit for Stage 3 (default from config)")
    p.add_argument("--clear", action="store_true", help="Clear discovery_candidates table before first run (use when polluted)")
    p.add_argument("--once", action="store_true", help="Run one cycle and exit (no repeat loop)")
    p.add_argument("--x-only", dest="x_only", action="store_true", help="Stage 1: fetch only X (TwitterAPI.io), skip news/RSS (quick X test)")
    p.add_argument("--entity-resolution", dest="entity_resolution", type=str, default="deepseek",
                    choices=["deepseek", "perplexity", "minimax"],
                    help="Stage 1.5: which LLM to use for entity resolution (default: deepseek)")
    args = p.parse_args()

    def _run():
        run_discovery(
            max_new_per_run=args.max_new,
            run_gtm_scan=not args.no_gtm_scan,
            max_articles_per_query=args.max_articles,
            sieve_threshold=args.sieve_threshold,
            stage=args.stage,
            clear=args.clear,
            x_only=getattr(args, "x_only", False),
            entity_resolution_provider=getattr(args, "entity_resolution", "deepseek"),
        )

    if args.once or args.stage is not None:
        _run()
    else:
        while True:
            try:
                if args.clear:
                    _run()
                    args.clear = False  # clear only on first cycle
                else:
                    _run()
                logger.info("Cycle complete. Sleeping 30 minutes before next discovery run...")
                time.sleep(1800)  # 30 min
            except Exception as e:
                logger.error(f"Cycle failed: {e}. Retrying in 10 minutes...", exc_info=True)
                time.sleep(600)  # 10 min
