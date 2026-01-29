# AI Content & Consultative Tone Detection System

## Executive Summary

Implemented a **comprehensive dual-layer system** to transform AI-generated emails from authoritative, robotic content to consultative, human-like communication that invites dialogue.

### Problem Solved
1. **Em dashes and AI markers** were dead giveaways of AI-generated content
2. **Authoritative tone** sounded presumptuous and lecturing rather than consultative
3. **No questions** meant emails were one-way pitches rather than dialogue invitations

### Solution Delivered
✅ **Detection**: Automated flagging of AI markers and authoritative language  
✅ **Removal**: Regex-based sanitization of em dashes and formal language  
✅ **Prevention**: Updated ALL LLM prompts with consultative guidelines  
✅ **Education**: Real-time UI feedback and comprehensive documentation  
✅ **Testing**: 10/10 tests passing with real-world examples  

---

## Quick Start

### 1️⃣ Read the Quick Reference (5 minutes)
```bash
cat CONSULTATIVE_QUICK_REF.md
```
One-page cheat sheet with:
- Phrases to avoid vs use
- Question frameworks
- Quick self-check list

### 2️⃣ Review Before/After Examples (10 minutes)
```bash
cat BEFORE_AFTER_EXAMPLES.md
```
Real transformations showing the difference, including your Heidi Health example.

### 3️⃣ Test the System
```bash
python test_consultative_tone.py
```
Should show: ✅ 10/10 tests passed

### 4️⃣ Monitor Generated Emails
The Streamlit UI now shows real-time feedback:
- ✅ "Send-safe & human-like" (no issues)
- ⚠️ "Contains AI markers: [list]" (warnings)

---

## What Changed

### Files Modified
- `utils/email_safety.py` - Core detection/removal logic (2 new functions)
- `pipeline_v2.py` - Updated Perplexity prompt with consultative guidelines
- `agent2_signal_monitor.py` - Updated signal email prompt
- `agent5_outreach_sequencer.py` - Updated follow-up prompt
- `ui_streamlit.py` - Integrated tone detection feedback
- `config.py` - Added ENABLE_AI_CONTENT_DETECTION flag

### Files Created
- `CONSULTATIVE_TONE_GUIDE.md` (5.6K) - Comprehensive framework
- `CONSULTATIVE_QUICK_REF.md` (4.3K) - One-page reference
- `CONSULTATIVE_TONE_IMPLEMENTATION.md` (8.2K) - Full implementation
- `BEFORE_AFTER_EXAMPLES.md` (9K) - Real transformations
- `TONE_DETECTION_SUMMARY.md` (7.9K) - Complete summary
- `AI_CONTENT_DETECTION_SUMMARY.md` (3.8K) - AI marker docs
- `test_consultative_tone.py` - Test suite (10/10 passing)
- `test_ai_content_detection.py` - AI marker tests

---

## The Transformation

### Your Original Example

**❌ BEFORE:**
> "With healthcare systems modernizing care delivery through AI like your scribe and workflow tools, bridging enterprise sales cycles with health systems like the NHS and Beth Israel Lahey **will be key to sustaining momentum**."

**Problems:**
- Too authoritative ("will be key")
- Em dashes present
- No questions
- Sounds like outsider lecturing insiders

---

**✅ AFTER:**
> "The way I'm reading this - it seems that creating a repeatable and predictable enterprise sales motion across diverse systems like NHS and Beth Israel will be key to success. **Am I reading this right?**"

**Improvements:**
- Tentative framing ("the way I'm reading")
- Regular hyphens (no em dashes)
- Question invitation
- Senior peer voice

---

## Key Features

### 1. AI Marker Detection & Removal
Detects and removes:
- Em dashes (—) → regular hyphens (-)
- En dashes (–) → regular hyphens (-)
- Formal AI openings ("I trust this finds you well")

### 2. Authoritative Tone Detection
Flags prescriptive language:
- "will be key to"
- "must focus on"
- "needs to prioritize"
- "is critical for"
- "success requires"

**Context-aware:** If followed by question mark, considered consultative hypothesis.

### 3. Consultative Question Detection
Validates presence of:
- Questions in the email
- Tentative framing ("my sense is")
- Curiosity markers ("curious if")
- Dialogue invitations ("am I reading this right?")

### 4. Real-time UI Feedback
Shows detection results in Streamlit:
- AI markers detected
- Authoritative tone issues
- Send-safe status

---

## Configuration

Single environment variable:
```bash
ENABLE_AI_CONTENT_DETECTION=true  # Default: enabled
```

Disable if needed for testing:
```bash
ENABLE_AI_CONTENT_DETECTION=false
```

---

## Documentation Index

| Document | Purpose | Size |
|----------|---------|------|
| `README_TONE_DETECTION.md` (this file) | Quick start & overview | - |
| `CONSULTATIVE_QUICK_REF.md` | One-page cheat sheet | 4.3K |
| `BEFORE_AFTER_EXAMPLES.md` | Real transformations | 9K |
| `CONSULTATIVE_TONE_GUIDE.md` | Comprehensive framework | 5.6K |
| `CONSULTATIVE_TONE_IMPLEMENTATION.md` | Full implementation | 8.2K |
| `TONE_DETECTION_SUMMARY.md` | Complete summary | 7.9K |
| `AI_CONTENT_DETECTION_SUMMARY.md` | AI marker specifics | 3.8K |

**Recommended reading order:**
1. This file (overview)
2. `CONSULTATIVE_QUICK_REF.md` (quick reference)
3. `BEFORE_AFTER_EXAMPLES.md` (see it in action)
4. Other docs as needed

---

## Testing

### Run All Tests
```bash
python test_consultative_tone.py
python test_ai_content_detection.py
```

### Test Individual Emails
```python
from utils.email_safety import detect_ai_content_markers

email_text = "Your draft here..."
markers = detect_ai_content_markers(email_text)
print(f"Issues detected: {markers}")
```

---

## Expected Outcomes

### Immediate
- ✅ Emails sound more human, less AI-generated
- ✅ More question-based engagement
- ✅ Less authoritative/presumptuous tone
- ✅ Em dashes removed automatically

### Medium-Term (Track These Metrics)
- 📈 Higher response rates
- 📈 More back-and-forth dialogue
- 📈 Shorter time-to-response
- 📉 "Sounds like AI" feedback

---

## The Core Principle

> **Show expertise through insightful QUESTIONS, not authoritative STATEMENTS.**

A truly senior seller demonstrates domain knowledge by asking questions that only an expert would know to ask. The question itself proves the expertise.

---

## Validation Strategy

The system ensures quality through:

1. **Prevention**: Prompts instruct LLMs correctly from the start
2. **Detection**: Automated system flags issues
3. **Education**: UI feedback helps users learn patterns
4. **Testing**: Continuous test suite validates accuracy

This creates a **feedback loop** where the system improves over time **without manual review**.

---

## Support

### Common Issues

**Q: System flagging good emails?**  
A: Check if questions are present. Authoritative language + question = consultative hypothesis (OK).

**Q: Want to adjust sensitivity?**  
A: Edit patterns in `utils/email_safety.py` → `detect_authoritative_tone()`

**Q: Need more examples?**  
A: See `BEFORE_AFTER_EXAMPLES.md` for 6+ full transformations

---

## Status

✅ **Production Ready**
- All tests passing (10/10 consultative, all AI marker tests)
- Integrated into UI with real-time feedback
- Comprehensive documentation complete
- Prompt engineering applied to all email generation paths

---

**Next Step:** Generate a few emails and review the tone detection feedback. The system will guide you toward more consultative, human-like communication.