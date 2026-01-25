"""
Ollama client for local LLM inference (free, no API costs).
Supports Qwen, Llama, and other Ollama models.
"""
import logging
import requests
from typing import Optional, Dict, Any
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"

def call_ollama(
    prompt: str,
    model: str = "qwen2.5:32b-instruct-q4_K_M",
    system_prompt: Optional[str] = None,
    response_format: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2000
) -> str:
    """
    Call local Ollama model for inference using the chat endpoint.
    """
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        if response_format == "json":
            data["format"] = "json"
        
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=data,
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("message", {}).get("content", "")
        else:
            error_msg = f"Ollama error {response.status_code}: {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        raise

def is_ollama_available() -> bool:
    """Check if Ollama is running and available."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False

def list_ollama_models() -> list:
    """List available Ollama models."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        return []
    except:
        return []

if __name__ == "__main__":
    # Test Ollama connection
    if is_ollama_available():
        print("✅ Ollama is running")
        models = list_ollama_models()
        print(f"Available models: {models}")
        
        # Test inference
        if models:
            test_model = models[0]
            print(f"\nTesting {test_model}...")
            response = call_ollama("Say 'Hello, I am working!' in exactly 5 words.", model=test_model)
            print(f"Response: {response}")
    else:
        print("❌ Ollama is not running. Start it with: ollama serve")
