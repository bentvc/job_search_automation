#!/usr/bin/env python3
"""Test MiniMax M2.1 via Anthropic-compatible API"""
import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

def test_minimax():
    api_key = os.getenv('MINIMAX_API_KEY')
    
    print("="*80)
    print("Testing MiniMax M2.1 via Anthropic-compatible API")
    print("="*80)
    
    client = Anthropic(
        api_key=api_key,
        base_url="https://api.minimax.io/anthropic"
    )
    
    try:
        message = client.messages.create(
            model="MiniMax-M2.1",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": "Write a brief professional email introducing yourself as a sales executive. 2-3 sentences only."
            }]
        )
        
        print("\n✅ SUCCESS!")
        print("\nResponse:")
        for block in message.content:
            if hasattr(block, 'type'):
                if block.type == 'thinking':
                    print(f"\n[Thinking]: {block.thinking[:100]}...")
                elif block.type == 'text':
                    print(f"\n{block.text}")
            elif hasattr(block, 'text'):
                print(f"\n{block.text}")
        
        print(f"\nUsage: {message.usage}")
        print("\n" + "="*80)
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        print("="*80)

if __name__ == "__main__":
    test_minimax()
