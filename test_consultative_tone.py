#!/usr/bin/env python3
"""
Test script for consultative tone detection in email drafts.
"""

from utils.email_safety import detect_authoritative_tone, detect_ai_content_markers

def test_consultative_tone_detection():
    """Test detection of authoritative vs consultative tone."""
    
    print("🧪 Testing Consultative Tone Detection\n")
    print("=" * 80)
    
    test_cases = [
        {
            "name": "AUTHORITATIVE (Bad Example from User)",
            "text": """With healthcare systems modernizing care delivery through AI like your scribe and workflow tools, 
bridging enterprise sales cycles with health systems like the NHS and Beth Israel Lahey will be key to sustaining momentum.""",
            "expected_issues": ["prescriptive_will_be", "no_questions_consultative_miss", "authoritative_without_curiosity"],
            "should_flag": True
        },
        {
            "name": "CONSULTATIVE (Good Example from User)",
            "text": """The way I'm reading this - it seems that creating a repeatable and predictable enterprise sales motion 
across diverse systems like NHS and Beth Israel and a lot of others I know will be key to success. Am I reading this right?""",
            "expected_issues": [],  # Has question, tentative language
            "should_flag": False
        },
        {
            "name": "Prescriptive 'Must'",
            "text": """To succeed in this market, you must focus on building repeatable processes and must prioritize 
enterprise relationships. The challenge is aligning sales and product teams.""",
            "expected_issues": ["prescriptive_must", "assertive_challenge", "no_questions_consultative_miss"],
            "should_flag": True
        },
        {
            "name": "Prescriptive 'Needs to'",
            "text": """Your company needs to address the gap between product-market fit and scalable sales. 
Success requires building a distributed team.""",
            "expected_issues": ["prescriptive_needs", "prescriptive_success", "no_questions_consultative_miss"],
            "should_flag": True
        },
        {
            "name": "Consultative with Curiosity",
            "text": """Based on what I'm seeing with the Series B, my sense is that scaling the payer sales motion 
might be the next challenge. Curious if that's where you're headed?""",
            "expected_issues": [],  # Has question + tentative language
            "should_flag": False
        },
        {
            "name": "Question-based Engagement",
            "text": """I've helped two companies navigate this exact transition - from early traction to predictable enterprise motion. 
Is that the phase you're in? Does that resonate?""",
            "expected_issues": [],  # Multiple questions, consultative
            "should_flag": False
        },
        {
            "name": "Authoritative without Questions",
            "text": """Scaling your sales organization is critical for growth. You need to build repeatable processes, 
hire the right talent, and align with product teams. This will be key to hitting your revenue targets.""",
            "expected_issues": ["prescriptive_needs", "prescriptive_will_be", "no_questions_consultative_miss"],
            "should_flag": True
        },
        {
            "name": "Humble Expertise",
            "text": """I could be wrong, but it seems like the transition from founder-led sales to a distributed team 
is the tricky part. In similar situations I've seen [specific challenge]. Sound right?""",
            "expected_issues": [],  # Has question + tentative language
            "should_flag": False
        },
        {
            "name": "Short Email with Question (OK)",
            "text": """Saw the funding news - congrats! Worth a quick chat Thursday?""",
            "expected_issues": [],  # Short emails don't need consultative markers
            "should_flag": False
        },
        {
            "name": "Multiple Authoritative Phrases",
            "text": """To capture this market opportunity, you must prioritize enterprise sales. 
Building a scalable motion is critical for success. Your team needs to focus on repeatability. 
The challenge is aligning incentives across sales and product.""",
            "expected_issues": ["prescriptive_must", "prescriptive_needs", "assertive_challenge", "no_questions_consultative_miss"],
            "should_flag": True
        }
    ]
    
    results = {"passed": 0, "failed": 0}
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['name']}")
        print("-" * 80)
        print(f"Text: {test_case['text'][:150]}...")
        
        # Detect authoritative tone issues
        auth_issues = detect_authoritative_tone(test_case['text'])
        
        print(f"\n✓ Detected issues: {auth_issues}")
        print(f"✓ Expected issues: {test_case['expected_issues']}")
        
        # Check if we correctly flagged/didn't flag
        has_issues = len(auth_issues) > 0
        should_flag = test_case['should_flag']
        
        if has_issues == should_flag:
            print(f"✅ PASS: Correctly {'flagged' if should_flag else 'cleared'}")
            results["passed"] += 1
        else:
            print(f"❌ FAIL: Should have {'flagged' if should_flag else 'cleared'} but didn't")
            results["failed"] += 1
        
        # Show key indicators
        question_count = test_case['text'].count('?')
        consultative_markers = ["my sense", "seems like", "am I reading", "does that resonate", 
                               "curious", "wondering", "could be wrong"]
        has_consultative = any(marker in test_case['text'].lower() for marker in consultative_markers)
        
        print(f"  • Questions: {question_count}")
        print(f"  • Has consultative markers: {has_consultative}")
        print(f"  • Issue count: {len(auth_issues)}")
    
    print("\n" + "=" * 80)
    print(f"\n📊 RESULTS: {results['passed']}/{len(test_cases)} tests passed")
    print(f"   Passed: {results['passed']}")
    print(f"   Failed: {results['failed']}")
    
    if results['failed'] == 0:
        print("\n✅ All tests passed! Tone detection working correctly.")
    else:
        print(f"\n⚠️  {results['failed']} test(s) failed. Review detection logic.")

def test_full_email_example():
    """Test the full email example provided by the user."""
    
    print("\n\n" + "=" * 80)
    print("🔍 Testing Real User Example")
    print("=" * 80)
    
    bad_example = """Subject: Scaling US Sales for Heidi's AI Care Partner Amid Rapid Global Expansion

Dear Hiring Team,

Heidi Health's recent $65M raise to accelerate global expansion - powering 10M+ consults monthly across 116 countries - marks a pivotal moment for US market penetration, especially as you're hiring to build out sales leadership. With healthcare systems modernizing care delivery through AI like your scribe and workflow tools, bridging enterprise sales cycles with health systems like the NHS and Beth Israel Lahey will be key to sustaining momentum.

As a senior enterprise sales leader with 15+ years building $90M+ books of business in payer/health plan segments (Medicaid, Medicare Advantage, commercial), I've closed multiple 7-figure, multi-year SaaS contracts in complex, long-cycle deals. My expertise in driving pipeline generation, GTM strategy, and executive relationships directly aligns with leading your US sales function - overseeing SDRs, AEs, and Solution Architects to acquire, expand, and retain customers across providers and payers.

I've thrived in ambiguity, translating vision into velocity while scaling teams and processes for predictable growth. I'd welcome a conversation on how my track record can support Heidi's US ambitions.

Best regards,
Bent Christiansen"""
    
    print("\n📧 ORIGINAL EMAIL (Authoritative):")
    print("-" * 80)
    print(bad_example[:400] + "...\n")
    
    # Detect all issues
    auth_issues = detect_authoritative_tone(bad_example)
    all_markers = detect_ai_content_markers(bad_example)
    
    print("🚨 DETECTED ISSUES:")
    print(f"  • Authoritative tone issues: {auth_issues}")
    print(f"  • All AI markers: {all_markers}")
    print(f"  • Question marks: {bad_example.count('?')}")
    
    print("\n💡 SUGGESTED IMPROVEMENTS:")
    print("-" * 80)
    print("""
Replace authoritative assertion:
  ❌ "bridging enterprise sales cycles with health systems like the NHS and Beth Israel Lahey 
      will be key to sustaining momentum"
  
With consultative question:
  ✅ "The way I'm reading this - creating a repeatable enterprise sales motion across diverse 
      systems like NHS and Beth Israel will be critical. Am I reading this right?"

Add dialogue invitation:
  ❌ "I'd welcome a conversation on how my track record can support Heidi's US ambitions."
  
  ✅ "Worth a brief chat to explore how this experience might apply? Open Thursday if helpful."

Make expertise tentative:
  ❌ "My expertise...directly aligns with leading your US sales function"
  
  ✅ "This background might be relevant for scaling the US motion - curious if that's the challenge?"
    """)

if __name__ == "__main__":
    test_consultative_tone_detection()
    test_full_email_example()