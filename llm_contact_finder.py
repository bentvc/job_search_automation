import os
import json
import logging
from typing import List, Dict, Any
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def find_contacts_via_perplexity(company_name: str, target_roles: str = "Sales Leadership") -> List[Dict[str, Any]]:
    """
    Uses Perplexity API to research specific individuals at a company.
    Returns a list of dicts: {name, title, source_url, notes}
    """
    load_dotenv(override=True)
    api_key = os.getenv("PERPLEXITY_API_KEY")
    
    if not api_key:
        logger.error("Missing PERPLEXITY_API_KEY")
        return []

    url = "https://api.perplexity.ai/chat/completions"
    
    prompt = f"""
    Find 3-5 specific, current senior leaders at '{company_name}' who match the profile: {target_roles}.
    Focus on finding their actual Names and exact Job Titles.
    
    Return ONLY a JSON object with a key "contacts" containing a list of objects.
    Each object must have:
    - "name": Full name
    - "title": Job title
    - "linkedin_url": LinkedIn URL if found, else null
    - "reason": Why they are a good target (1 sentence)
    
    Do not include markdown formatting like ```json. Just raw JSON.
    """

    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "You are a precise B2B lead researcher. Return JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }

    try:
        response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200:
            logger.error(f"Perplexity API error: {response.text}")
            return []
            
        content = response.json()['choices'][0]['message']['content']
        # Clean markdown if present
        content = content.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(content)
        contacts = data.get("contacts", [])
        
        # Add metadata
        for c in contacts:
            c['source'] = 'perplexity_ai'
            
        return contacts
        
    except Exception as e:
        logger.error(f"Error parsing Perplexity response: {e}")
        return []
