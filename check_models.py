import os
import google.generativeai as genai
from anthropic import Anthropic
import config

print("Checking Google Models...")
try:
    genai.configure(api_key=config.GOOGLE_API_KEY)
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Google: {m.name}")
except Exception as e:
    print(f"Google Error: {e}")

print("\nChecking Anthropic...")
try:
    # Anthropic doesn't have a list_models() API like Google
    print("Anthropic doesn't support model discovery. Trying 'claude-3-5-sonnet-latest'...")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}]
    )
    print(f"Anthropic Success with 'claude-3-5-sonnet-latest'")
except Exception as e:
    print(f"Anthropic Error: {e}")
