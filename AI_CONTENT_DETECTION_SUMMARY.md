# AI Content Detection & Removal System

## Overview
Implemented a comprehensive system to detect and remove AI-generated content markers that make emails sound artificial and robotic. The primary focus is on **em dashes (—)** which are a major giveaway for AI-generated content.

## Features Implemented

### 1. Detection System (`utils/email_safety.py`)
- **Em dash detection**: Identifies `—` characters in email content
- **En dash detection**: Identifies `–` characters  
- **AI-typical formal openings**: Detects phrases like "I trust this finds you well"
- **Excessive punctuation patterns**: Flags multiple em dashes as suspicious
- **Word connector patterns**: Detects `word—word` constructions

### 2. Removal/Sanitization System
- **Em dash replacement**: `word—word` → `word - word` (with spaces)
- **Contextual replacements**: `phrase—and` → `phrase, and`
- **En dash normalization**: `–` → `-` (regular hyphen)
- **Formal opening removal**: Strips AI-typical greetings
- **Whitespace normalization**: Cleans up spacing after replacements

### 3. LLM Prompt Updates
Updated all email generation prompts to include:
```
CRITICAL WRITING GUIDELINES:
- Use ONLY standard punctuation: periods, commas, regular hyphens (-), question marks, exclamation points
- NEVER use em dashes (—) or en dashes (–) - these are AI content giveaways
- Avoid overly formal openings like "I trust this finds you well"
- Write naturally as a human would, not as an AI assistant
- Use contractions where natural (I've, we've, that's)
```

**Files updated:**
- `pipeline_v2.py` (Perplexity system prompt)
- `agent2_signal_monitor.py` (Signal-based email generation)
- `agent5_outreach_sequencer.py` (Follow-up email generation)

### 4. UI Integration (`ui_streamlit.py`)
- **Real-time feedback**: Shows AI markers detected in email drafts
- **Visual indicators**: 
  - ✅ "Send-safe & human-like" (no issues)
  - ⚠️ "Send-safe but contains AI markers: [list]" (warnings)
- **Non-blocking**: AI markers don't prevent sending, just warn

### 5. Configuration Control
- **Environment variable**: `ENABLE_AI_CONTENT_DETECTION=true/false`
- **Default**: Enabled by default
- **Granular control**: Can disable detection/removal if needed

## Testing
Created comprehensive test suite (`test_ai_content_detection.py`) that validates:
- Em dash detection and removal
- En dash normalization  
- AI formal opening detection
- Mixed marker scenarios
- Clean human-like text (no false positives)

## Example Transformations

### Before (AI-generated):
```
Hi John,

Saw the news about the Series B—congrats. The platform—built for scale—handles complex workflows efficiently.

I hope this message finds you well.
```

### After (Humanized):
```
Hi John,

Saw the news about the Series B - congrats. The platform - built for scale - handles complex workflows efficiently.

```

## Impact
- **Reduces AI detection risk**: Removes obvious AI content markers
- **Improves deliverability**: More human-like emails less likely to be flagged
- **Maintains quality**: Non-destructive transformations preserve meaning
- **Configurable**: Can be disabled if needed for testing

## Files Modified
- `utils/email_safety.py` - Core detection and removal logic
- `pipeline_v2.py` - Updated Perplexity prompt
- `agent2_signal_monitor.py` - Updated signal email prompt  
- `agent5_outreach_sequencer.py` - Updated follow-up prompt
- `ui_streamlit.py` - Added real-time AI marker feedback
- `config.py` - Added configuration option
- `utils.py` - Fixed example email
- `test_ai_content_detection.py` - Comprehensive test suite

## Configuration
Set in `.env` or environment:
```bash
ENABLE_AI_CONTENT_DETECTION=true  # Default: enabled
```

The system provides a balanced approach - detecting and removing obvious AI markers while preserving the natural flow and meaning of the emails.