import json
import logging
import time
from typing import Optional, Dict, Any
import openai
from anthropic import Anthropic
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for discovered models and blocked status
DISCOVERED_MODELS = {
    'openai': None,
    'anthropic': None,
    'deepseek': None,
    'google': None,
    'openrouter': None
}

BLOCKED_PROVIDERS = {} # provider -> expiry_time

def discover_best_model(provider: str, api_key: str) -> str:
    """
    Discovers the best available model for a provider if not already cached.
    """
    if DISCOVERED_MODELS[provider]:
        return DISCOVERED_MODELS[provider]

    try:
        if provider == 'openai':
            DISCOVERED_MODELS[provider] = config.DEFAULT_OPENAI_MODEL
            
        elif provider == 'deepseek':
            DISCOVERED_MODELS[provider] = config.DEFAULT_DEEPSEEK_MODEL

        elif provider == 'anthropic':
            client = Anthropic(api_key=api_key)
            available = [m.id for m in client.models.list().data]
            logger.info(f"Available Anthropic models: {available}")
            
            # Priority patterns: 4.5 > 4.1 > 4 > 3.7 > 3.5
            patterns = ['4-5', '4-1', '4-', '3-7', '3-5', '3-']
            for pattern in patterns:
                matches = [m for m in available if pattern in m and 'haiku' not in m]
                if matches:
                    DISCOVERED_MODELS[provider] = matches[0]
                    break
            
        elif provider == 'google':
            DISCOVERED_MODELS[provider] = "gemini-1.5-flash" # Standard dependable default
        
        elif provider == 'openrouter':
            DISCOVERED_MODELS[provider] = config.DEFAULT_OPENROUTER_MODEL
                
        logger.info(f"Discovered best {provider} model: {DISCOVERED_MODELS[provider]}")
        return DISCOVERED_MODELS[provider]
        
    except Exception as e:
        logger.error(f"Discovery failed for {provider}: {e}")
        return None

def call_llm(prompt: str, model: Optional[str] = None, response_format: Optional[str] = None, forced_provider: Optional[str] = None) -> str:
    """
    Robust LLM call with dynamic discovery, caching, and multi-provider failover.
    """
    now = time.time()
    
    # Priority ordered list, except if forced_provider is set
    all_providers = [
        ('openai', config.OPENAI_API_KEY, "https://api.openai.com/v1"),
        ('openrouter', config.OPENROUTER_API_KEY, "https://openrouter.ai/api/v1"),
        ('anthropic', config.ANTHROPIC_API_KEY, None),
        ('google', config.GOOGLE_API_KEY, None),
        ('deepseek', config.DEEPSEEK_API_KEY, "https://api.deepseek.com")
    ]
    
    # Re-order if forced_provider is set
    if forced_provider:
        match = [p for p in all_providers if p[0] == forced_provider]
        rest = [p for p in all_providers if p[0] != forced_provider]
        providers = match + rest
    else:
        providers = all_providers

    for provider_name, api_key, base_url in providers:
        if not api_key or 'your_' in str(api_key):
            continue
            
        if provider_name in BLOCKED_PROVIDERS and now < BLOCKED_PROVIDERS[provider_name]:
            logger.info(f"Skipping {provider_name} (on cooldown)")
            continue

        target_model = model or discover_best_model(provider_name, api_key)
        if not target_model:
            continue

        try:
            if provider_name in ['openai', 'deepseek', 'openrouter']:
                client = openai.OpenAI(api_key=api_key, base_url=base_url)
                args = {
                    "model": target_model,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if provider_name == 'openrouter':
                    args["extra_headers"] = {
                        "HTTP-Referer": "https://antigravity.ai", # Optional
                        "X-Title": "Antigravity Sales Copilot"
                    }
                if response_format == "json":
                    args["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**args, timeout=45)
                return response.choices[0].message.content

            elif provider_name == 'anthropic':
                client = Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=target_model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text

            elif provider_name == 'google':
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model_obj = genai.GenerativeModel(target_model)
                # Google format differs
                resp = model_obj.generate_content(prompt)
                return resp.text

        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"{provider_name.capitalize()} failed with model {target_model}: {e}")
            
            if any(x in error_str for x in ['quota', '429', 'rate', 'limit', 'insufficient']):
                BLOCKED_PROVIDERS[provider_name] = now + 600
                logger.warning(f"Blocking {provider_name} for 10 minutes.")
            
            if any(x in error_str for x in ['404', 'not_found', 'not found']):
                DISCOVERED_MODELS[provider_name] = None
                logger.warning(f"Clearing model discovery cache for {provider_name}.")
                
            continue

    return "Error: All available LLM providers failed or were on cooldown."

def parse_json_from_llm(content: str) -> Dict[str, Any]:
    """
    Attempts to parse JSON from LLM response, handling markdown blocks if present.
    """
    try:
        if "```json" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[-1].split("```")[0].strip()
        
        return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}. Content: {content}")
        return {}
