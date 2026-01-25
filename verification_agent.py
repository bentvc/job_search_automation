"""
Verification Agent using Perplexity API to fact-check draft emails before sending.
Prevents hallucinations and false claims about companies.
"""
import logging
import os
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

def verify_claims_with_perplexity(company_name: str, draft_email: str, candidate_vertical: str = "healthcare") -> Dict[str, Any]:
    """
    Use Perplexity to verify factual claims made in the draft email.
    
    Returns:
        {
            "is_valid": bool,
            "issues_found": list of problems,
            "verification_notes": string,
            "confidence": 0-100
        }
    """
    if not PERPLEXITY_API_KEY:
        logger.warning("PERPLEXITY_API_KEY not set, skipping verification")
        return {"is_valid": True, "issues_found": [], "verification_notes": "Verification skipped - no API key", "confidence": 0}
    
    # Extract potential factual claims from the email
    verification_prompt = f"""
    I need to verify factual claims in this outreach email to {company_name}.
    
    Email draft:
    {draft_email}
    
    Candidate background: {candidate_vertical} sales professional
    
    Please verify:
    1. Does {company_name} actually operate in the {candidate_vertical} sector?
    2. Are there any false claims about {company_name}'s business, products, or market focus?
    3. Does the email incorrectly attribute {candidate_vertical}-specific activities to {company_name}?
    
    Be specific about what's true and what's false. Cite sources.
    """
    
    try:
        response = requests.post(
            f"{PERPLEXITY_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sonar-pro",  # Uses real-time web search with citations
                "messages": [
                    {"role": "system", "content": "You are a fact-checking assistant. Verify claims and cite sources."},
                    {"role": "user", "content": verification_prompt}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            verification_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Parse verification result
            issues = []
            is_valid = True
            
            # Look for STRONG red flags only (be less sensitive)
            red_flags = [
                f"{company_name} does not operate in {candidate_vertical}",
                f"{company_name} is not a {candidate_vertical} company",
                f"{company_name} has no presence in {candidate_vertical}",
                "completely false",
                "entirely incorrect",
                "no evidence whatsoever"
            ]
            
            verification_lower = verification_text.lower()
            for flag in red_flags:
                if flag.lower() in verification_lower:
                    is_valid = False
                    issues.append(f"Potential false claim detected: {flag}")
            
            # Calculate confidence based on verification clarity
            confidence = 90 if is_valid else 30
            
            return {
                "is_valid": is_valid,
                "issues_found": issues,
                "verification_notes": verification_text,
                "confidence": confidence
            }
        else:
            logger.error(f"Perplexity API error: {response.status_code}")
            return {"is_valid": False, "issues_found": ["Verification API failed"], "confidence": 0}
            
    except Exception as e:
        logger.error(f"Perplexity verification failed: {e}")
        return {"is_valid": False, "issues_found": [f"Verification error: {str(e)}"], "confidence": 0}

def get_company_vertical(company_name: str) -> Dict[str, Any]:
    """
    Use Perplexity to accurately determine a company's actual vertical/industry.
    
    Returns:
        {
            "primary_vertical": string,
            "description": string,
            "is_healthcare": bool,
            "is_fintech": bool,
            "confidence": 0-100
        }
    """
    if not PERPLEXITY_API_KEY:
        return {"primary_vertical": "unknown", "description": "", "is_healthcare": False, "is_fintech": False, "confidence": 0}
    
    query = f"""
    What is {company_name}'s primary industry vertical and business focus?
    
    Provide:
    1. Main industry/vertical (be specific)
    2. Brief description of what they do
    3. Whether they have significant healthcare business (yes/no)
    4. Whether they have significant fintech business (yes/no)
    
    Be factual and cite sources.
    """
    
    try:
        response = requests.post(
            f"{PERPLEXITY_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sonar-pro",
                "messages": [
                    {"role": "system", "content": "You are a business research assistant. Provide accurate, sourced information about companies."},
                    {"role": "user", "content": query}
                ]
            },
            timeout=20
        )
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Parse the response
            response_lower = response_text.lower()
            
            # Determine primary vertical from response
            verticals = {
                "devops": ["devops", "ci/cd", "gitlab", "github"],
                "cybersecurity": ["cybersecurity", "security", "infosec", "threat"],
                "saas": ["saas", "software as a service"],
                "healthcare": ["healthcare", "health plan", "payer", "medical"],
                "fintech": ["fintech", "payments", "banking", "financial"],
            }
            
            detected_vertical = "general"
            for vertical, keywords in verticals.items():
                if any(kw in response_lower for kw in keywords):
                    detected_vertical = vertical
                    break
            
            is_healthcare = any(kw in response_lower for kw in ["healthcare", "health plan", "payer", "medical", "hospital"])
            is_fintech = any(kw in response_lower for kw in ["fintech", "payment", "banking", "financial services"])
            
            return {
                "primary_vertical": detected_vertical,
                "description": response_text,
                "is_healthcare": is_healthcare,
                "is_fintech": is_fintech,
                "confidence": 85
            }
        else:
            logger.error(f"Perplexity API error: {response.status_code}")
            return {"primary_vertical": "unknown", "description": "", "is_healthcare": False, "is_fintech": False, "confidence": 0}
            
    except Exception as e:
        logger.error(f"Company vertical lookup failed: {e}")
        return {"primary_vertical": "unknown", "description": "", "is_healthcare": False, "is_fintech": False, "confidence": 0}

if __name__ == "__main__":
    # Test with GitLab (should detect it's NOT healthcare)
    print("Testing verification with GitLab...")
    
    vertical_info = get_company_vertical("GitLab")
    print(f"\nGitLab vertical info:")
    print(f"  Primary: {vertical_info['primary_vertical']}")
    print(f"  Is healthcare: {vertical_info['is_healthcare']}")
    print(f"  Description: {vertical_info['description'][:200]}...")
    
    # Test verification of false claim
    bad_draft = """Hi Bill,
    
Your work at GitLab in the healthcare sector caught my attention. With 15+ years in Healthcare/Digital Health, 
I wanted to share insights about payer/provider markets where GitLab is making significant strides."""
    
    verification = verify_claims_with_perplexity("GitLab", bad_draft, "healthcare")
    print(f"\nVerification result:")
    print(f"  Valid: {verification['is_valid']}")
    print(f"  Issues: {verification['issues_found']}")
    print(f"  Confidence: {verification['confidence']}%")
