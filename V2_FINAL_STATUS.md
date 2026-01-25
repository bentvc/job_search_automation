# ✅ V2 Pipeline Implementation Summary

## Completed

### 1. Core Implementation
**File**: `pipeline_v2.py` (403 lines)

**Key Functions**:
- `deepseek_analyze_and_draft()` - Stage 1: Local analysis + initial draft
- `perplexity_finalize()` - Stage 2: Web verification + final email
- `run_v2_pipeline()` - Complete two-stage flow
- `determine_status()` - Auto-classify ready vs needs_review

**Features**:
- JSON validation with auto-retry
- Graceful error handling and fallbacks
- Local (free) or API DeepSeek options
- Web-grounded Perplexity verification with citations

### 2. Database Schema
**Added 8 new columns** to `ProactiveOutreach`:

**DeepSeek Stage**:
- `ds_wedge` - Strategic angle
- `ds_rationale` - Why this wedge
- `ds_key_points` - Proof points (JSON)
- `ds_raw_draft` - First-pass email

**Perplexity Stage**:
- `px_final_email` - Send-ready email
- `px_confidence` - 0-1 factual confidence
- `px_factual_flags` - Unverified claims (JSON)
- `px_citations` - Sources (JSON)

**Legacy fields preserved** for backward compatibility.

### 3. UI Updates
**File**: `ui_streamlit.py`

**Right Panel - Analysis Section**:
```
🧠 DeepSeek Strategy
├─ Wedge badge
├─ Rationale (collapsible)
├─ Proof Points (collapsible)
└─ DeepSeek Draft (collapsible)

🌐 Perplexity Final
├─ Confidence badge (🟢/🟡/🔴)
├─ Factual Flags (if any)
├─ Citations (collapsible)
└─ Status indicator

Actions:
[🚀 Run DeepSeek] [🌐 Run Perplexity]
```

**Middle Panel - Email Editor**:
- Now uses `px_final_email` if available
- Falls back to legacy `draft_email`
- Updates correct field on edit

**Legacy Support**:
- Shows "Legacy Council (Deprecated)" label for old records
- Suggests regeneration with V2 pipeline

### 4. Cost Language (Softened)
**Before**: "$0.012/record", "$0.002/record", "83% savings"
**After**: "DeepSeek is free; Perplexity adds roughly a cent per outreach"

**Speed Language** (Softened):
**Before**: "30-45s DeepSeek, 15-20s Perplexity, 50s total"
**After**: "Typically 30-90 seconds per record (varies by system and network)"

### 5. Configuration
**File**: `config.py`
- `USE_V2_PIPELINE = true` (default)
- `ENABLE_EXPERIMENTAL_COUNCIL = false` (legacy disabled)

## Architecture

### Two-Stage Flow
```
DeepSeek (local, FREE)
  ↓ Analyze company/role
  ↓ Choose strategic wedge
  ↓ Generate initial draft
  ↓
Perplexity (online, ~1¢)
  ↓ Verify facts via web search
  ↓ Polish tone & language
  ↓ Return final email + confidence + flags
  ↓
Status: ready / needs_review
```

### Strategic Wedges (7 options)
1. Value-Based Care (VBC/risk/quality)
2. Utilization Management (prior auth/UM)
3. Payment Integrity (claims/fraud/audit)
4. Network & Access (provider networks)
5. Care Navigation (member engagement)
6. Risk Adjustment (HCC coding/RAF)
7. General Enterprise SaaS (if not healthcare)

### Status Rules
- **ready**: confidence ≥ 0.85, no flags
- **ready**: confidence ≥ 0.70, ≤1 minor flag
- **needs_review**: confidence < 0.70 or multiple flags

## What's Next

### Immediate
1. ✅ Core pipeline implemented
2. ✅ Database schema updated
3. ✅ UI shows two-stage flow
4. ⏳ Test V2 pipeline on real data
5. ⏳ Create batch regeneration script

### Testing
Current test (`test_v2_pipeline.py`) was stopped due to long DeepSeek inference time (local CPU).

**Options**:
1. Test with faster hardware
2. Use DeepSeek API instead of local
3. Test on smaller/simpler company first

### Batch Regeneration
**Next step**: Create script to process all queued records:
```python
# regenerate_v2_pipeline.py
for outreach in session.query(ProactiveOutreach).filter_by(status='queued'):
    result = run_v2_pipeline(...)
    # Save all ds_* and px_* fields
    session.commit()
```

## Files Modified

1. ✅ `pipeline_v2.py` - Core V2 implementation (NEW)
2. ✅ `config.py` - Added V2 pipeline flags
3. ✅ `models.py` - Added V2 columns to ProactiveOutreach
4. ✅ `ui_streamlit.py` - Two-stage display, legacy support
5. ✅ `test_v2_pipeline.py` - Test script (NEW)
6. ✅ `V2_PIPELINE.md` - Documentation (NEW)
7. ✅ `V2_IMPLEMENTATION_COMPLETE.md` - Summary (NEW)

## Key Benefits

1. **Simpler** - 2 stages vs 4+, clearer logic
2. **Cheaper** - DeepSeek free, Perplexity ~1¢/outreach
3. **Better** - Web-verified facts with citations
4. **Clearer** - Explicit wedge strategy, no black box
5. **Flexible** - Local or API DeepSeek, graceful fallbacks

## UI Status

**Streamlit running**: `http://localhost:8501`

**View the new V2 display**:
1. Open UI
2. Select any outreach record
3. Right panel shows:
   - DeepSeek Strategy (if `ds_*` fields populated)
   - Perplexity Final (if `px_*` fields populated)
   - Legacy Council (if only old `insights` field)

## Summary

✅ **V2 Pipeline fully implemented** with:
- Clean two-stage architecture
- Database schema support
- Updated UI with two-stage display
- Softened cost/speed claims
- Legacy council disabled by default
- Graceful backward compatibility

**Ready for**: Testing on real data and batch regeneration.
