"""
V2 Pipeline: DeepSeek → Perplexity

Simple two-stage outreach generation.
- Stage 1: DeepSeek (local, FREE) - Analyze & draft
- Stage 2: Perplexity (online, ~1¢/outreach) - Verify & finalize

Cost: DeepSeek is free; Perplexity adds roughly a cent per outreach.
Speed: Typically 30-90 seconds per record (varies by system and network).
"""
import json
import logging
import os
import requests
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================================
# DeepSeek Stage: Local Analysis + Draft
# ============================================================================

DEEPSEEK_SYSTEM_PROMPT = """
You are a senior B2B healthtech sales leader. Focus on strategic analysis.

TASK:
1) Choose ONE primary "wedge" (angle of approach) from: 
   Value-Based Care, Utilization Management, Payment Integrity, Network & Access, Care Navigation, Risk Adjustment, General Enterprise SaaS / GTM.
2) Provide 3-5 rationale_bullets explaining why this wedge fits the target company/role.
3) Provide 3-6 proof_points from the sender's profile that support this wedge.

Return JSON with keys: wedge, rationale_bullets, proof_points.
"""

def normalize_wedge_and_angle(outreach_data: Dict[str, Any], company_vertical: str):
    """
    Guardrail: If not healthcare, force generic wedge and remove 'healthcare focus' phrasing.
    """
    vertical = (company_vertical or "").lower()
    is_healthcare = any(word in vertical for word in ["health", "payer", "provider", "medical", "clinical", "oncology", "pharma"])
    
    if not is_healthcare:
        # Force generic wedge if it's currently healthcare-specific
        ds_wedge = outreach_data.get("ds_wedge")
        healthcare_wedges = ["Value-Based Care", "Utilization Management", "Payment Integrity", "Network & Access", "Care Navigation", "Risk Adjustment"]
        if ds_wedge in healthcare_wedges:
            outreach_data["ds_wedge"] = "General Enterprise SaaS / GTM"

        # Strip healthcare focus phrasing from fit_explanation if present
        fit_explanation = outreach_data.get("fit_explanation")
        if fit_explanation:
            # Generalize this: remove common healthcare-heavy phrasing
            replacements = {
                "alignment with GitLab's healthcare focus": "alignment with GitLab's DevOps and developer productivity focus",
                "alignment with the company's healthcare focus": "alignment with their strategic growth focus",
                "alignment with their healthcare focus": "alignment with their strategic growth focus",
                "payer/healthcare markets": "complex B2B and enterprise software markets",
                "healthcare markets": "enterprise and DevOps markets",
                "healthcare focus": "enterprise SaaS focus",
                "payer market": "enterprise market"
            }
            
            new_explanation = fit_explanation
            for old, new in replacements.items():
                # Case insensitive replace
                import re
                new_explanation = re.sub(re.escape(old), new, new_explanation, flags=re.IGNORECASE)
            
            outreach_data["fit_explanation"] = new_explanation

def deepseek_analyze_and_draft(
    company: str,
    role: str,
    job_description: str,
    sender_profile: str,
    use_local: bool = True,
    company_vertical: Optional[str] = None
) -> Dict[str, Any]:
    """
    Stage 1: DeepSeek analyzes the opportunity and produces strategic wedge + proof points.
    """
    # Truncate job description to avoid token limits
    job_desc_truncated = job_description[:4000] if job_description else "No description provided"
    
    user_prompt = f"""
Target Company: {company}
Target Role: {role}
Company Vertical: {company_vertical or 'Unknown'}

Job Description:
{job_desc_truncated}

Sender Profile:
{sender_profile}

Analyze this opportunity and produce the strategic JSON output.
"""
    
    try:
        if use_local:
            # Use local DeepSeek via Ollama
            from ollama_client import call_ollama
            logger.info(f"DeepSeek (local) analyzing {company}...")
            
            response_text = call_ollama(
                prompt=user_prompt,
                model="deepseek-r1:32b",
                system_prompt=DEEPSEEK_SYSTEM_PROMPT,
                response_format="json",
                max_tokens=1000,
                temperature=0.4
            )
        else:
            # Use DeepSeek API
            from utils import call_llm
            logger.info(f"DeepSeek (API) analyzing {company}...")
            
            full_prompt = f"{DEEPSEEK_SYSTEM_PROMPT}\n\n{user_prompt}"
            response_text = call_llm(
                prompt=full_prompt,
                forced_provider='deepseek',
                response_format='json'
            )
        
        # Parse JSON
        parsed = json.loads(response_text)
        
        # Validate structure
        required_keys = ["wedge", "rationale_bullets", "proof_points"]
        for key in required_keys:
            if key not in parsed:
                raise ValueError(f"Missing required key: {key}")
        
        # Apply normalization guardrail
        if company_vertical:
            normalize_wedge_and_angle(parsed, company_vertical)

        # Create a sketch for the UI/Stage 2 instead of a full draft
        proof_text = "; ".join(parsed.get("proof_points", []))
        parsed["email_draft"] = f"STRATEGY: Use {parsed.get('wedge')} wedge. HIGHLIGHT: {proof_text}"
        
        logger.info(f"✅ DeepSeek completed strategy for {company}")
        return parsed
        
    except Exception as e:
        logger.error(f"DeepSeek stage failed for {company}: {e}")
        return {
            "wedge": "General Enterprise SaaS",
            "rationale_bullets": ["Fallback used due to analysis error"],
            "proof_points": ["15+ years enterprise sales experience"],
            "email_draft": "DeepSeek analysis failed. Proceeding with fallback strategy.",
            "error": str(e)
        }


# ============================================================================
# Perplexity Stage: Web-Grounded Finalization
# ============================================================================

PERPLEXITY_SYSTEM_PROMPT = """
You are an expert enterprise sales leader writing high-stakes outbound emails to C-suite leaders in healthtech.

TASK:
1) Use the web to research the target company's current priorities, products, and market position.
2) Write a compelling, concise outbound email (150-220 words).
3) You MUST use the strategic "wedge" and "proof points" provided by the previous analysis.
4) Tone: Senior, professional, non-salesy, and high-value. Focus on how the sender's specific experience solves a problem relevant to the wedge.

Return ONLY valid JSON with:
{
  "final_email": "string",
  "confidence": 0.0-1.0,
  "factual_flags": ["list of any unverified claims"],
  "citations": ["list of key URLs used"]
}
"""

def perplexity_finalize(
    company: str,
    role: str,
    job_description: str,
    job_url: Optional[str],
    sender_profile: str,
    ds_wedge: str,
    ds_rationale: str,
    ds_proof_points: list,
    ds_raw_draft: str,
    contact_name: Optional[str] = None,
    contact_title: Optional[str] = None,
    company_vertical: Optional[str] = None
) -> Dict[str, Any]:
    """
    Stage 2: Perplexity researches the company and writes the final email based on DeepSeek's strategy.
    """
    PPLX_API_KEY = os.getenv('PERPLEXITY_API_KEY')
    
    if not PPLX_API_KEY:
        logger.error("PERPLEXITY_API_KEY not set!")
        return {
            "final_email": f"ERROR: No Perplexity API key found. Strategy was: {ds_wedge}",
            "confidence": 0.0,
            "factual_flags": ["Missing API Key"],
            "citations": []
        }
    
    job_desc_truncated = job_description[:3000] if job_description else "No description"
    proof_points_text = "\n- ".join(ds_proof_points) if ds_proof_points else "None"
    
    user_prompt = f"""
Target Company: {company}
Target Role: {role}
Company Vertical / Segment: {company_vertical or 'Unknown'}
Job URL: {job_url or 'N/A'}

Target Contact:
Name: {contact_name or 'Unknown'}
Title: {contact_title or 'Unknown'}
Company: {company}

Job Description:
{job_desc_truncated}

Sender Profile:
{sender_profile}

STRATEGIC SIGNAL (from DeepSeek):
Wedge: {ds_wedge}
Rationale: {ds_rationale}
Proof Points to Highlight:
- {proof_points_text}

TASK:
1) Research {company} to find a specific, recent hook (funding, new product, market shift) that fits the {ds_wedge} wedge.
2) GROUNDING: This company's vertical is {company_vertical or 'Unknown'}. When describing alignment, emphasize enterprise SaaS / DevOps experience rather than healthcare, unless the vertical explicitly includes healthcare.
3) Write the full outbound email from scratch addressed to {contact_name or 'the recipient'} by name in the greeting.
4) Do NOT just polish a draft; craft a fresh, researched email based on the strategy above.
5) Output ONLY valid JSON.
"""
    
    max_retries = 2
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Perplexity finalizing {company} (web search enabled, attempt {attempt + 1})...")
            
            payload = {
                "model": "sonar-pro",  # Uses web search
                "messages": [
                    {"role": "system", "content": PERPLEXITY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 1500,
                "temperature": 0.3
            }
            
            headers = {
                "Authorization": f"Bearer {PPLX_API_KEY}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            # Catch 5xx errors for retry
            if 500 <= response.status_code < 600:
                raise requests.exceptions.HTTPError(f"{response.status_code} Server Error")
            
            if response.status_code != 200:
                # Non-5xx errors (like 4xx) typically shouldn't be retried
                logger.error(f"Perplexity API non-retryable error: {response.status_code} - {response.text}")
                return {
                    "final_email": None,
                    "confidence": 0.0,
                    "factual_flags": [f"Perplexity call failed: HTTP {response.status_code}"],
                    "citations": []
                }
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            # Parse JSON - will raise JSONDecodeError if invalid
            parsed = json.loads(content)
            
            # Validate structure
            if "final_email" not in parsed:
                raise ValueError("Missing 'final_email' in Perplexity response")
            
            # Ensure confidence is a number
            if "confidence" not in parsed or not isinstance(parsed["confidence"], (int, float)):
                parsed["confidence"] = 0.7  # Default
            
            if "factual_flags" not in parsed:
                parsed["factual_flags"] = []
            
            logger.info(f"✅ Perplexity completed for {company} (confidence: {parsed['confidence']:.2f})")
            return parsed
            
        except (json.JSONDecodeError, requests.exceptions.RequestException, ValueError) as e:
            if attempt < max_retries:
                logger.warning(f"Perplexity attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            else:
                logger.error(f"Perplexity stage finally failed for {company} after {max_retries + 1} attempts: {e}")
                return {
                    "final_email": None,
                    "confidence": 0.0,
                    "factual_flags": [f"Perplexity call failed: {str(e)[:100]}"],
                    "citations": []
                }


# ============================================================================
# Complete Pipeline
# ============================================================================

def _has_valid_deepseek_output(ds_result: Dict[str, Any]) -> bool:
    """
    True only if we have valid ds_wedge, ds_rationale, ds_key_points, and ds_raw_draft.
    We do NOT call Perplexity on blank or incomplete DeepSeek output except for special cases.
    """
    wedge = ds_result.get("wedge")
    rationale = ds_result.get("rationale_bullets")
    proof_points = ds_result.get("proof_points")
    draft = ds_result.get("email_draft")
    
    if not wedge or not isinstance(wedge, str) or not wedge.strip():
        return False
    if not rationale or not isinstance(rationale, list) or len(rationale) == 0:
        return False
    if not proof_points or not isinstance(proof_points, list) or len(proof_points) == 0:
        return False
    if not draft or not isinstance(draft, str) or not draft.strip():
        return False
    
    return True


def run_v2_pipeline(
    company: str,
    role: str,
    job_description: str,
    job_url: Optional[str],
    sender_profile: str,
    use_local_deepseek: bool = True,
    contact_name: Optional[str] = None,
    contact_title: Optional[str] = None,
    company_vertical: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete two-stage pipeline: DeepSeek → Perplexity
    
    We always call deepseek_analyze_and_draft() first. We only call perplexity_finalize()
    once we have valid ds_wedge, ds_rationale, ds_key_points, and ds_raw_draft.
    We do not call Perplexity on completely blank records except for special cases we explicitly code.
    
    Returns both stages' outputs in a single dict for easy persistence.
    """
    # Stage 1: DeepSeek (always run first)
    ds_result = deepseek_analyze_and_draft(
        company=company,
        role=role,
        job_description=job_description,
        sender_profile=sender_profile,
        use_local=use_local_deepseek,
        company_vertical=company_vertical
    )
    
    ds_wedge = ds_result.get("wedge")
    ds_rationale = "\n".join(ds_result.get("rationale_bullets", []))
    ds_key_points = ds_result.get("proof_points", [])
    ds_raw_draft = ds_result.get("email_draft", "")
    
    # Stage 2: Perplexity — only when we have valid DeepSeek output
    if _has_valid_deepseek_output(ds_result):
        px_result = perplexity_finalize(
            company=company,
            role=role,
            job_description=job_description,
            job_url=job_url,
            sender_profile=sender_profile,
            ds_wedge=ds_wedge or "",
            ds_rationale=ds_rationale,
            ds_proof_points=ds_key_points,
            ds_raw_draft=ds_raw_draft,
            contact_name=contact_name,
            contact_title=contact_title,
            company_vertical=company_vertical
        )
        status = determine_status(px_result)
        px_final_email = px_result.get("final_email")
        px_confidence = px_result.get("confidence")
        px_factual_flags = px_result.get("factual_flags")
        px_citations = px_result.get("citations")
    else:
        # Skip Perplexity: incomplete or blank DeepSeek output
        logger.warning(
            f"Skipping Perplexity for {company}: missing or invalid DeepSeek output "
            "(wedge, rationale_bullets, proof_points, email_draft). Fix DeepSeek stage first."
        )
        px_final_email = None
        px_confidence = None
        px_factual_flags = None
        px_citations = None
        status = "drafted"  # DeepSeek done, Perplexity not run
    
    return {
        "ds_wedge": ds_wedge,
        "ds_rationale": ds_rationale,
        "ds_key_points": ds_key_points,
        "ds_raw_draft": ds_raw_draft,
        "px_final_email": px_final_email,
        "px_confidence": px_confidence,
        "px_factual_flags": px_factual_flags,
        "px_citations": px_citations,
        "status": status,
    }


def determine_status(px_result: Dict[str, Any]) -> str:
    """
    Simple rule: if confidence high and no flags, mark as ready.
    Otherwise needs review.
    """
    confidence = px_result.get("confidence", 0)
    flags = px_result.get("factual_flags", [])
    
    if confidence >= 0.85 and not flags:
        return "ready"
    elif confidence >= 0.70 and len(flags) <= 1:
        return "ready"  # Minor flags OK
    else:
        return "needs_review"
