import requests
import logging
import config
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def _org_search_variants(company_name: str) -> List[str]:
    """
    Generate a small set of fallback org-name queries.
    Apollo often stores brands as shorter names (e.g. 'Heidi' vs 'Heidi Health').
    """
    if not company_name:
        return []
    raw = company_name.strip()
    if not raw:
        return []

    variants: List[str] = []
    def _add(v: str):
        v = (v or "").strip()
        if v and v not in variants:
            variants.append(v)

    _add(raw)

    # Remove common suffix tokens
    import re
    cleaned = re.sub(r"\b(inc|inc\.|llc|ltd|corp|co|company|health|healthcare|group|systems)\b", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    _add(cleaned)

    # If multi-word, try first 1-2 tokens (brand shorthand)
    parts = [p for p in re.split(r"\s+", raw) if p]
    if len(parts) >= 2:
        _add(parts[0])
        _add(" ".join(parts[:2]))

    # If we removed suffixes into one token, try that token
    parts2 = [p for p in re.split(r"\s+", cleaned) if p]
    if len(parts2) == 1:
        _add(parts2[0])

    return variants[:5]

def _log_payload(payload: dict, max_len: int = 800) -> str:
    try:
        s = json.dumps(payload, default=str)
    except Exception:
        s = str(payload)
    return (s[:max_len] + "...") if len(s) > max_len else s

def _log_response_keys(data: dict) -> str:
    try:
        return str(list(data.keys()))
    except Exception:
        return "non-dict-json"

class ApolloClient:
    """
    Client for interacting with the Apollo.io API to find decision makers.
    """
    BASE_URL = "https://api.apollo.io/api/v1"

    def __init__(self, api_key: str = None):
        # Force reload .env to ensure fresh key
        from dotenv import load_dotenv
        import os
        load_dotenv(override=True)
        
        self.api_key = api_key or os.getenv('APOLLO_API_KEY')
        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
            "Cache-Control": "no-cache"
        }

    def search_organizations(self, company_name: str) -> List[Dict[str, Any]]:
        """
        Search for an organization by name to find its domain.
        Uses /mixed_companies/search (API v1).
        """
        if not self.api_key or "your_" in self.api_key:
            return []

        endpoint = f"{self.BASE_URL}/mixed_companies/search"
        attempts = _org_search_variants(company_name)
        if not attempts:
            return []

        # Collect candidates across variants, then choose best match.
        # This avoids returning irrelevant hits like "Heidi Health Foundation"
        # when the real brand is stored as a shorter name (e.g. "Heidi").
        candidates_by_id: Dict[str, Dict[str, Any]] = {}
        try_queries: List[str] = []

        # Normalizers for scoring
        import re
        def _norm(s: str) -> str:
            s = (s or "").lower().strip()
            s = re.sub(r"\b(inc|inc\.|llc|ltd|corp|co|company|health|healthcare|group|systems|foundation)\b", "", s)
            s = re.sub(r"[^a-z0-9]+", "", s)
            return s

        target_norm = _norm(company_name)
        primary_token = (company_name or "").strip().split(" ")[0] if company_name else ""
        primary_norm = _norm(primary_token)

        for q in attempts:
            payload = {"q_organization_name": q, "page": 1, "per_page": 10}
            try:
                try_queries.append(q)
                logger.info(f"[Apollo] POST {endpoint} payload={_log_payload(payload)}")
                logger.info(f"Sending Apollo request with Key: {self.api_key[:4]}...{self.api_key[-4:] if self.api_key else 'None'}")
                response = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
                logger.info(f"[Apollo] status={response.status_code}")

                if response.status_code != 200:
                    logger.error(f"Apollo org search failed: {response.status_code} - {response.text}")
                    continue

                data = response.json()
                logger.info(f"[Apollo] Reponse keys: {_log_response_keys(data)}")
                orgs = data.get("organizations") or data.get("accounts") or []
                for o in (orgs or []):
                    oid = o.get("id")
                    if oid and oid not in candidates_by_id:
                        candidates_by_id[oid] = o

            except Exception as e:
                logger.error(f"Apollo org search error (q='{q}'): {e}")
                continue

        candidates = list(candidates_by_id.values())
        if not candidates:
            return []

        def _score_org(o: Dict[str, Any]) -> int:
            name = o.get("name") or ""
            n = _norm(name)
            domain = (o.get("primary_domain") or o.get("domain") or o.get("website_url") or "").lower()

            score = 0
            if domain:
                score += 40
            if n == target_norm:
                score += 80
            if primary_norm and n == primary_norm:
                score += 60
            if target_norm and target_norm in n:
                score += 25
            if primary_norm and primary_norm in n:
                score += 20
            if primary_norm and domain and primary_norm in domain:
                score += 35

            # Penalize common false positives
            lname = name.lower()
            if "foundation" in lname:
                score -= 200
            if "counselor" in lname or "mental health" in lname:
                score -= 150

            return score

        candidates.sort(key=_score_org, reverse=True)
        best = candidates[0]
        if best and best.get("name"):
            logger.info(f"[Apollo] Org selected '{best.get('name')}' from queries={try_queries}")

        return candidates[:3]

    def search_people(self, company_domain: str = None, titles: List[str] = None, organization_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Search for people. Can use company_domain OR organization_ids.
        """
        if not self.api_key or "your_" in self.api_key:
            return []

        endpoint = f"{self.BASE_URL}/mixed_people/api_search"
        
        # IMPORTANT: callers pass titles=None to indicate a broad search.
        # We still provide default titles for relevance, but we must NOT
        # apply "verified only" gating in that case.
        titles_were_provided = titles is not None
        if not titles:
            titles = config.APOLLO_TARGET_TITLES

        payload = {
            "person_titles": titles,
            "page": 1,
            "per_page": 50, # Boosted for local filtering
            # Only strict if titles were explicitly provided by caller
            "contact_email_status": ["verified"] if titles_were_provided else []
        }
        
        if organization_ids:
            payload["organization_ids"] = organization_ids
        elif company_domain:
            payload["q_organization_domains"] = company_domain
        else:
            return []

        try:
            logger.info(f"[Apollo] POST {endpoint} payload={_log_payload(payload)}")
            
            response = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
            logger.info(f"[Apollo] status={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"[Apollo] Response keys: {_log_response_keys(data)}")
                people = data.get("people", [])
                logger.info(f"Apollo found {len(people)} contacts")
                return people
            else:
                logger.error(f"Apollo search failed: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Apollo request error: {e}")
            return []

    def enrich_organization(self, domain: str) -> Dict[str, Any]:
        """
        Get detailed company data from Apollo.
        """
        if not self.api_key or "your_" in self.api_key:
            return {}

        endpoint = f"{self.BASE_URL}/organizations/enrich"
        params = {
            "domain": domain
        }

        try:
            response = requests.get(endpoint, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("organization", {})
        except Exception as e:
            logger.error(f"Apollo enrichment error: {e}")
        return {}

    def enrich_person_by_name(self, name: str, company_domain: str = None, company_name: str = None) -> List[Dict[str, Any]]:
        """
        Search for a specific person by name at a company to get their email.
        """
        if not self.api_key or "your_" in self.api_key:
            return []

        endpoint = f"{self.BASE_URL}/mixed_people/api_search"
        
        payload = {
            "q_keywords": name,
            "page": 1,
            "per_page": 2
        }
        
        if company_domain:
            payload["q_organization_domains"] = company_domain
        elif company_name:
            # Fallback to org search if no domain
            orgs = self.search_organizations(company_name)
            if orgs:
                dom = orgs[0].get('primary_domain') or orgs[0].get('domain')
                if dom:
                    payload["q_organization_domains"] = dom

        try:
            logger.info(f"Enriching {name} via Apollo...")
            response = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                people = data.get("people", [])
                
                results = []
                for p in people:
                    # Double check name fuzzy match
                    # (Apollo sometimes returns loose matches)
                    p_name = f"{p.get('first_name','')} {p.get('last_name','')}"
                    if name.lower().split()[0] in p_name.lower(): # Match at least first name
                         results.append({
                            'name': p_name.strip(),
                            'title': p.get('title'),
                            'email': p.get('email'),
                            'linkedin_url': p.get('linkedin_url'),
                            'apollo_id': p.get('id'),
                            'source': 'apollo_from_ai'
                         })
                return results
            return []
        except Exception as e:
            logger.error(f"Apollo enrichment error for {name}: {e}")
            return []

    def unlock_person_email(self, person_id: str) -> Dict[str, Any]:
        """
        Pay a credit to unlock/enrich a specific person's email.
        Returns a diagnostic dict wrapper.
        """
        if not self.api_key: return {"error": "No API Key"}
        
        # Try direct Person Lookup by ID first
        endpoint = f"{self.BASE_URL}/people/{person_id}"
        payload = {} # GET request
        
        out = {
            "endpoint": endpoint,
            "method": "GET",
            "http_status": None,
            "raw_response": None,
            "parsed_person": None
        }
        
        try:
            logger.info(f"[Apollo] GET {endpoint}")
            
            resp = requests.get(endpoint, headers=self.headers, timeout=10)
            out["http_status"] = resp.status_code
            logger.info(f"[Apollo] status={resp.status_code}")
            
            try:
                data = resp.json()
                out["raw_response"] = data
                logger.info(f"[Apollo] Response keys: {_log_response_keys(data)}")
                
                # Check directly for person object (GET /people/:id usually returns the object directly or {"person": ...})
                if "person" in data:
                    out["parsed_person"] = data["person"]
                elif "id" in data: # sometimes returns the person directly
                    out["parsed_person"] = data
                    
            except Exception:
                out["raw_response"] = resp.text[:1000]
                
        except Exception as e:
            logger.error(f"Failed to unlock {person_id}: {e}")
            out["error"] = str(e)
            
        return out
        
    def reveal_person_email(self, person_id: str) -> Dict[str, Any]:
        """
        Pay a credit to REVEAL a specific person's email using /people/bulk_match.
        Uses ID-based matching.
        """
        if not self.api_key: return {"error": "No API Key"}
        
        endpoint = f"{self.BASE_URL}/people/bulk_match"
        
        payload = {
            "details": [{"id": person_id}],
            "reveal_personal_emails": True
        }
        
        out = {
            "endpoint": endpoint,
            "method": "POST",
            "payload_sent": payload,
            "http_status": None,
            "raw_response": None,
            "parsed_person": None,
            "credits_consumed": None
        }
        
        try:
            logger.info(f"[Apollo] POST {endpoint} payload={_log_payload(payload)}")
            
            resp = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
            out["http_status"] = resp.status_code
            logger.info(f"[Apollo] status={resp.status_code}")
            
            try:
                data = resp.json()
                out["raw_response"] = data
                out["credits_consumed"] = data.get("credits_consumed")
                logger.info(f"[Apollo] Response keys: {_log_response_keys(data)}")
                
                matches = data.get("matches", [])
                if matches:
                    out["parsed_person"] = matches[0]
                    logger.info(f"[Apollo] Matches[0] keys: {_log_response_keys(matches[0])}")
                    
            except Exception:
                out["raw_response"] = resp.text[:1000]
                
        except Exception as e:
            logger.error(f"Failed to reveal {person_id}: {e}")
            out["error"] = str(e)
            
        return out

import json
import os

ENRICHMENT_CACHE_FILE = "data/contact_enrichment.json"

def _load_enrichment_cache() -> Dict[str, Any]:
    if not os.path.exists(ENRICHMENT_CACHE_FILE):
        return {}
    try:
        with open(ENRICHMENT_CACHE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_enrichment_cache(person_id: str, data: Dict[str, Any]):
    cache = _load_enrichment_cache()
    # Merge existing to avoid data loss if we fetch partial updates
    # But usually we want the latest full object
    cache[person_id] = data
    
    os.makedirs(os.path.dirname(ENRICHMENT_CACHE_FILE), exist_ok=True)
    with open(ENRICHMENT_CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def get_enriched_data(person_id: str) -> Dict[str, Any]:
    cache = _load_enrichment_cache()
    return cache.get(person_id)

def find_contacts_for_lead(company_name: str, title_query: str, limit: int = 3) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Wrapper to find contacts for a specific lead.
    Returns: (contacts_list, debug_info_dict)
    """
    client = ApolloClient()
    debug_info = {"company_input": company_name, "title_query": title_query}
    debug_info["active_key_masked"] = f"{client.api_key[:4]}...{client.api_key[-4:] if client.api_key else 'None'}"
    
    # 1. Resolve Org Domain
    logger.info(f"Resolving domain for {company_name}...")
    orgs = client.search_organizations(company_name)
    if not orgs:
        debug_info["error"] = "Company domain resolution failed (0 orgs found)"
        return [], debug_info
    
    # Use first match
    first_org = orgs[0]
    
    # Robust extraction helpers inline
    def _clean_domain(val):
        if not isinstance(val, str):
            return None
        val = val.strip()
        if not val:
            return None
        return val.replace("https://", "").replace("http://", "").strip("/")
        
    domain = _clean_domain(first_org.get('primary_domain')) or \
             _clean_domain(first_org.get('domain')) or \
             _clean_domain(first_org.get('website_url'))
             
    org_id = first_org.get('id')
    
    debug_info["resolved_domain"] = domain
    debug_info["resolved_org_id"] = org_id
    debug_info["resolved_org_name"] = first_org.get('name') or "Unknown Org"
    
    if not domain and not org_id:
        debug_info["error"] = f"Org found but no domain/id. Keys: {list(first_org.keys())}"
        debug_info["org_dump"] = str(first_org)[:500]
        return [], debug_info

    # 2. Search People (Broadly first)
    # Strategy: Get many people, then filter/rank locally
    logger.info(f"Broad search at {domain} / ID {org_id}...")
    
    # We fetch more candidates to allow for local filtering
    candidates = []
    if org_id:
        candidates = client.search_people(organization_ids=[org_id], titles=None) # No titles = Broad
    elif domain:
        candidates = client.search_people(company_domain=domain, titles=None)
        
    debug_info["raw_people_count"] = len(candidates)
    
    # 3. Local Ranking & Filtering
    target_keywords = [t.strip().lower() for t in title_query.split(',')] if title_query else [
        "sales", "business", "growth", "revenue", "ceo", "founder", "president", 
        "partnerships", "channel", "commercial", "go-to-market"
    ]
    
    ranked_candidates = []
    
    for p in candidates:
        p_title = (p.get('title') or "").lower()
        score = 0
        
        # Relevance Score
        if any(k in p_title for k in target_keywords):
            score += 10
        if "vp" in p_title or "vice president" in p_title or "head" in p_title or "chief" in p_title:
            score += 5
        if p.get('email'):
            score += 20 # Prioritize existing emails
            
        ranked_candidates.append((score, p))
    
    # Sort by score descending
    ranked_candidates.sort(key=lambda x: x[0], reverse=True)
    
    # Select top results
    final_selection = [x[1] for x in ranked_candidates[:limit]]
    
    # If no matches found for specific keywords, fallback to just top seniority from the broad list
    if not final_selection and candidates:
         debug_info["fallback_used"] = "No keyword matches, showing top seniority"
         final_selection = candidates[:limit]
    
    # 4. Clean & Return
    results = []
    for p in final_selection:
        # Robust Name Construction (Allow partials)
        first = p.get('first_name', '').strip()
        last = p.get('last_name', '').strip()
        if first or last:
            full_name = f"{first} {last}".strip()
        else:
            full_name = p.get('name') or "Unknown Name"
            
        # Robust Email
        email = p.get('email') or p.get('email_address')
        
        # Raw Snapshot for Debugging
        raw_snapshot = {
            "id": p.get("id"),
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "name": p.get("name"),
            "email": p.get("email"),
            "email_status": p.get("email_status"),
            "contact_email_status": p.get("contact_email_status"),
            "linkedin_url": p.get("linkedin_url"),
            "organization": p.get("organization", {}).get("name")
        }
        
        results.append({
            'name': full_name,
            'title': p.get('title'),
            'email': email,
            'email_status': p.get('email_status') or p.get('contact_email_status'),
            'linkedin_url': p.get('linkedin_url'),
            'apollo_id': p.get('id'),
            'source': 'apollo_search',
            'raw_data': raw_snapshot
        })
    return results, debug_info


