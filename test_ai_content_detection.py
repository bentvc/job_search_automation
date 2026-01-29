#!/usr/bin/env python3
"""
Test script for AI content detection and removal functionality.
"""

from utils.email_safety import sanitize_email_text, detect_ai_content_markers, validate_send_safe

def test_ai_content_detection():
    """Test AI content marker detection and removal."""
    
    print("🧪 Testing AI Content Detection and Removal\n")
    
    # Test cases with AI-generated content markers
    test_cases = [
        {
            "name": "Em dash in company name",
            "input": "Hi John,\n\nSaw the news about the Series B—congrats. Scaling payer sales post-raise is often where the friction starts.",
            "expected_markers": ["contains_em_dash", "em_dash_word_connector"]
        },
        {
            "name": "Multiple em dashes",
            "input": "The platform—built for scale—handles complex workflows efficiently.",
            "expected_markers": ["contains_em_dash", "excessive_em_dashes_2", "em_dash_word_connector"]
        },
        {
            "name": "En dash usage",
            "input": "We target SMBs (5–500 employees) in the US market.",
            "expected_markers": ["contains_en_dash"]
        },
        {
            "name": "AI formal opening",
            "input": "I hope this message finds you well. I wanted to reach out about your recent funding.",
            "expected_markers": ["contains_formal_ai_opening"]
        },
        {
            "name": "Mixed AI markers",
            "input": "I trust this finds you well.\n\nThe company—especially post-Series B—is scaling rapidly.",
            "expected_markers": ["contains_em_dash", "contains_formal_ai_opening", "em_dash_word_connector"]
        },
        {
            "name": "Clean human-like text",
            "input": "Hi Sarah,\n\nCongrats on the Series B! I've helped two companies navigate the post-raise scaling challenges.\n\nWould love to chat Thursday?\n\nBest,\nBent",
            "expected_markers": []
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        print(f"Input: {test_case['input'][:100]}...")
        
        # Test detection
        detected_markers = detect_ai_content_markers(test_case['input'])
        print(f"Detected markers: {detected_markers}")
        print(f"Expected markers: {test_case['expected_markers']}")
        
        # Check if detection matches expectations
        detection_correct = set(detected_markers) == set(test_case['expected_markers'])
        print(f"Detection correct: {'✅' if detection_correct else '❌'}")
        
        # Test sanitization
        sanitized = sanitize_email_text(test_case['input'])
        print(f"Sanitized: {sanitized[:100]}...")
        
        # Test validation
        is_safe, reasons = validate_send_safe(sanitized)
        ai_reasons = [r for r in reasons if r.startswith("ai_marker_")]
        print(f"Validation: {'✅ Safe' if is_safe else '❌ Blocked'} (AI markers: {len(ai_reasons)})")
        
        print("-" * 80)
    
    # Test the specific example from utils.py
    print("\n🔍 Testing Real Example from Codebase:")
    real_example = 'Hi [Name],\n\nSaw the news about the Series B—congrats. Scaling payer sales post-raise is often where the friction starts.\n\nI\'ve built this motion twice (0-$50M), specifically navigating the complex contracting at UHC and Aetna. Would love to share how we structured the \'Pilot-to-Enterprise\' model to shorten cycles.\n\nOpen to a brief chat Thursday?\n\nBest,\nBent'
    
    print("Original:")
    print(real_example)
    print()
    
    markers = detect_ai_content_markers(real_example)
    print(f"Detected AI markers: {markers}")
    
    sanitized = sanitize_email_text(real_example)
    print("\nSanitized:")
    print(sanitized)
    
    is_safe, reasons = validate_send_safe(sanitized)
    print(f"\nValidation: {'✅ Safe to send' if is_safe else '❌ Blocked'}")
    print(f"Reasons: {reasons}")

if __name__ == "__main__":
    test_ai_content_detection()