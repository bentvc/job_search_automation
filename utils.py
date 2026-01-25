import json
import logging
import time
from typing import Optional, Dict, Any
import openai
from anthropic import Anthropic
import requests
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for discovered models and blocked status
DISCOVERED_MODELS = {
    'openai': None,
    'anthropic': None,
    'deepseek': None,
    'google': None,
    'openrouter': None,
    'minimax': None,
    'z': None
}

# Provider pricing (per 1M tokens)
PROVIDER_COSTS = {
    'minimax': 0.003,  # MiniMax M2.1 - cheapest
    'z': 0.005,        # z.ai - backup cheap option
    'deepseek': 0.014,
    'openrouter': 0.080,
    'openai': 0.150,   # Expensive - disabled
    'anthropic': 0.300, # Very expensive - disabled
    'google': 0.075
}

BLOCKED_PROVIDERS = {} # provider -> expiry_time

def discover_best_model(provider: str, api_key: str) -> str:
    """
    Discovers the best available model for a provider if not already cached.
    """
    if DISCOVERED_MODELS.get(provider):
        return DISCOVERED_MODELS[provider]

    try:
        if provider == 'openai':
            DISCOVERED_MODELS[provider] = config.DEFAULT_OPENAI_MODEL
            
        elif provider == 'deepseek':
            DISCOVERED_MODELS[provider] = config.DEFAULT_DEEPSEEK_MODEL

        elif provider == 'minimax':
            # MiniMax now uses Anthropic-compatible API
            DISCOVERED_MODELS[provider] = config.DEFAULT_MINIMAX_MODEL
            
        elif provider == 'z':
            DISCOVERED_MODELS[provider] = config.DEFAULT_Z_MODEL
            
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

def call_llm(prompt: str, model: Optional[str] = None, response_format: Optional[str] = None, forced_provider: Optional[str] = None, enable_expensive: bool = False) -> str:
    """
    Robust LLM call with dynamic discovery, caching, and multi-provider failover.
    
    Args:
        enable_expensive: If True, allow OpenAI/Anthropic. Default False to avoid costs.
    """
    now = time.time()
    
    # Priority ordered list (cheapest first, OpenAI/Anthropic disabled by default)
    all_providers = [
        ('minimax', config.MINIMAX_API_KEY, "anthropic"),  # Now uses Anthropic-compatible API
        ('z', config.Z_API_KEY, "https://api.z.ai/v1"),
        ('deepseek', config.DEEPSEEK_API_KEY, "https://api.deepseek.com"),
        ('openrouter', config.OPENROUTER_API_KEY, "https://openrouter.ai/api/v1"),
    ]
    
    # Add expensive providers only if explicitly enabled
    if enable_expensive:
        all_providers.extend([
            ('openai', config.OPENAI_API_KEY, "https://api.openai.com/v1"),
            ('anthropic', config.ANTHROPIC_API_KEY, None),
            ('google', config.GOOGLE_API_KEY, None)
        ])
    
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
            # MiniMax (Anthropic-compatible API)
            if provider_name == 'minimax':
                client = Anthropic(
                    api_key=api_key,
                    base_url="https://api.minimax.io/anthropic"
                )
                message = client.messages.create(
                    model=target_model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}]
                )
                # Extract text blocks (skip thinking)
                result = ""
                for block in message.content:
                    if hasattr(block, 'type') and block.type == 'text':
                        result += block.text
                    elif hasattr(block, 'text'):
                        result += block.text
                logger.info(f"✅ {provider_name} succeeded with {target_model}")
                return result
            
            # Anthropic (Native)
            elif provider_name == 'anthropic':
                client = Anthropic(api_key=api_key)
                message = client.messages.create(
                    model=target_model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}]
                )
                result = message.content[0].text
                logger.info(f"✅ {provider_name} succeeded with {target_model}")
                return result
            
            # OpenAI-compatible (OpenAI, DeepSeek, OpenRouter, z.ai)
            elif provider_name in ['openai', 'deepseek', 'openrouter', 'z']:
                client = openai.OpenAI(api_key=api_key, base_url=base_url)
                args = {
                    "model": target_model,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if provider_name == 'openrouter':
                    args["extra_headers"] = {
                        "HTTP-Referer": "https://antigravity.ai",
                        "X-Title": "Antigravity Sales Copilot"
                    }
                if response_format == "json" and provider_name not in ['z']:
                    args["response_format"] = {"type": "json_object"}
                
                completion = client.chat.completions.create(**args)
                     
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

    # FINAL FALLBACK: Mock Mode if User has no keys yet
    if "Council" in prompt or "personas" in prompt:
         logger.warning("⚠️ All providers failed. Using MOCK response for Council.")
         return mock_council_response(prompt)

    return "Error: All available LLM providers failed or were on cooldown."

def mock_council_response(prompt):
    """Returns a realistic mock response for the Council prompt."""
    import random
    angles = [
        "Focus on their recent Series B funding and need for scalable payer sales processes.",
        "Highlight your experience with UnitedHealthcare given their recent partnership announcement.",
        "Leverage the shared connection to the board member and mention the 'Speed to Value' case study.",
        "Pitch a 'Pilot-to-Enterprise' conversion model which fits their current product maturity."
    ]
    
    return json.dumps({
        "insights": f"**Angle 1 (Strategist):** {angles[0]}\n\n**Angle 2 (Dealmaker):** {angles[3]}\n\n**Council Decision:** The Strategist's approach aligns better with their conservative hiring culture.",
        "outreach_angle": "Series B Scaling & Payer Process",
        "draft_email": "Hi [Name],\n\nSaw the news about the Series B—congrats. Scaling payer sales post-raise is often where the friction starts.\n\nI've built this motion twice (0-$50M), specifically navigating the complex contracting at UHC and Aetna. Would love to share how we structured the 'Pilot-to-Enterprise' model to shorten cycles.\n\nOpen to a brief chat Thursday?\n\nBest,\nBent"
    })


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
