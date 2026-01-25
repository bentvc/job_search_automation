# V2 Pipeline Architecture

**Effective Date**: January 24, 2026  
**Status**: Primary pipeline (default)

## Overview

The V2 pipeline replaces the complex "council of experts" approach with a simple, cost-effective two-stage flow:

```
DeepSeek (local) → Perplexity (online) → Send
```

## Architecture

### Stage 1: DeepSeek Analysis (Local, FREE)

**Purpose**: Analyze opportunity, choose strategy wedge, generate first draft

**Model**: DeepSeek-R1:32b via Ollama (local inference, zero cost)

**Inputs**:
- Company name
- Role/title
- Job description
- Sender profile

**Outputs**:
- `ds_wedge`: Strategic angle (e.g., "Value-Based Care")
- `ds_rationale`: 3-5 bullets explaining why this wedge
- `ds_key_points`: 3-6 proof points from sender's background
- `ds_raw_draft`: First-pass email (150-200 words)

**Performance**:
- Time: ~30-45 seconds per record
- Cost: $0.00 (local inference)
- Quality: Strong reasoning, may need fact-checking

### Stage 2: Perplexity Finalization (Online, ~$0.002/record)

**Purpose**: Verify facts via web search, polish tone, produce final email

**Model**: Perplexity Sonar Pro (with web search + citations)

**Inputs**:
- All context from Stage 1
- Company/job details
- DeepSeek's wedge, rationale, proof points, and draft

**Outputs**:
- `px_final_email`: Send-ready email body
- `px_confidence`: 0-1 score (factual confidence)
- `px_factual_flags`: List of unverified/softened claims
- `px_citations`: Sources used (optional)

**Performance**:
- Time: ~15-20 seconds per record
- Cost: ~$0.002 per record
- Quality: Web-grounded, citation-backed

### Status Determination

After Perplexity stage:
- **ready**: confidence ≥ 0.85 and no flags
- **ready**: confidence ≥ 0.70 and ≤1 minor flag
- **needs_review**: confidence < 0.70 or multiple flags

## Data Model

### ProactiveOutreach (Updated)

```python
class ProactiveOutreach(Base):
    # ... existing fields ...
    
    # LEGACY (deprecated, use ds_* and px_* instead)
    insights = Column(Text, nullable=True)
    outreach_angle = Column(String, nullable=True)
    draft_email = Column(Text, nullable=True)
    
    # V2 PIPELINE: DeepSeek stage
    ds_wedge = Column(String, nullable=True)
    ds_rationale = Column(Text, nullable=True)
    ds_key_points = Column(JSON, nullable=True)
    ds_raw_draft = Column(Text, nullable=True)
    
    # V2 PIPELINE: Perplexity stage
    px_final_email = Column(Text, nullable=True)
    px_factual_flags = Column(JSON, nullable=True)
    px_confidence = Column(Numeric, nullable=True)
    px_citations = Column(JSON, nullable=True)
    
    status = Column(String(50), default='queued')
```

## Cost Comparison

### V2 Pipeline (Current)
```
DeepSeek (local):     $0.000
Perplexity (online):  $0.002
─────────────────────────────
Total per record:     $0.002

24 records:           $0.05
```

### Legacy Council (Disabled)
```
MiniMax analysis:     $0.004
Wedge identification: $0.002
Draft generation:     $0.004
Perplexity verify:    $0.002
─────────────────────────────
Total per record:     $0.012

24 records:           $0.29
```

**V2 saves 83% on generation costs** while maintaining quality through web verification.

## Configuration

### Enable V2 Pipeline (Default)
```bash
# .env
USE_V2_PIPELINE=true  # Default
```

### Enable Legacy Council (Experimental)
```bash
# .env
ENABLE_EXPERIMENTAL_COUNCIL=true
```

**Note**: Legacy council should NOT be used for routine outreach. It remains available only for experiments.

## Usage

### Generate Single Record

```python
from pipeline_v2 import run_v2_pipeline
import config

result = run_v2_pipeline(
    company="Gravie",
    role="CEO",
    job_description="...",
    job_url="https://...",
    sender_profile=config.USER_PROFILE_SUMMARY,
    use_local_deepseek=True  # FREE
)

# Save to database
outreach.ds_wedge = result['ds_wedge']
outreach.ds_rationale = result['ds_rationale']
outreach.ds_key_points = result['ds_key_points']
outreach.ds_raw_draft = result['ds_raw_draft']
outreach.px_final_email = result['px_final_email']
outreach.px_confidence = result['px_confidence']
outreach.px_factual_flags = result['px_factual_flags']
outreach.status = result['status']
db.commit()
```

### Batch Regeneration

```python
from pipeline_v2 import run_v2_pipeline
from database import SessionLocal
from models import ProactiveOutreach, Company, Contact
import config

session = SessionLocal()
outreaches = session.query(ProactiveOutreach).filter_by(status='queued').all()

for outreach in outreaches:
    company = session.query(Company).get(outreach.company_id)
    contact = session.query(Contact).get(outreach.contact_id)
    
    result = run_v2_pipeline(
        company=company.name,
        role=contact.title,
        job_description=...,
        job_url=...,
        sender_profile=config.USER_PROFILE_SUMMARY
    )
    
    # Update record
    outreach.ds_wedge = result['ds_wedge']
    # ... (set all fields)
    outreach.status = result['status']

session.commit()
```

## UI Updates Required

### Queue Panel (Left)
Update labels to show pipeline stage:
- 🔄 **Queued**: No processing yet
- 📝 **DeepSeek**: Has `ds_raw_draft`, needs Perplexity
- ✅ **Ready**: Has `px_final_email`, confidence ≥ 0.85
- ⚠️ **Review**: Has `px_final_email` but flags/low confidence

### Detail Panel (Right)
Replace "Council Insights" section with two-stage display:

**Section 1: DeepSeek Strategy**
- Wedge (badge/chip)
- Rationale (collapsible bullets)
- Proof Points (list)
- Raw Draft (collapsible text area)

**Section 2: Perplexity Final**
- Final Email (editable text area)
- Confidence Score (progress bar or badge)
- Factual Flags (warning list if any)
- Citations (collapsible list)

**Actions**:
- 🚀 "Run DeepSeek" (if no `ds_raw_draft`)
- 🌐 "Run Perplexity" (if no `px_final_email`)
- ✅ "Mark Ready" / "Send"

## Performance Targets

### Latency
- DeepSeek: 30-45s (local CPU inference)
- Perplexity: 15-20s (API call with web search)
- **Total**: ~50 seconds per record

### Cost
- DeepSeek: $0.00 (local)
- Perplexity: ~$0.002
- **Total**: $0.002 per record

### Quality
- Factual accuracy: 95%+ (web-verified)
- Confidence ≥ 0.85: 80-90% of records
- Manual review needed: 10-20% of records

### Throughput
- 24 records: ~20 minutes, $0.05 total
- 100 records: ~83 minutes, $0.20 total

## Strategic Wedges

DeepSeek can choose from these wedges:

1. **Value-Based Care**: VBC/risk arrangements/quality programs
2. **Utilization Management**: Prior auth/medical necessity/UM workflows
3. **Payment Integrity**: Claims accuracy/fraud detection/audit
4. **Network & Access**: Provider networks/credentialing/directories
5. **Care Navigation**: Member engagement/care coordination
6. **Risk Adjustment**: HCC coding/RAF scores
7. **General Enterprise SaaS**: If not healthcare-specific

## Troubleshooting

### DeepSeek Returns Invalid JSON
- Automatic retry with stricter "JSON only" instruction
- Temperature reduced from 0.4 to 0.2 on retry

### Perplexity Verification Fails
- Falls back to DeepSeek draft with warning flag
- Email marked as `needs_review`
- User can manually verify before sending

### Low Confidence Scores
- Check `px_factual_flags` for specific issues
- Manually review and edit `px_final_email`
- Consider whether company is good fit

## Migration Path

### Existing Records (Legacy Council Data)
- Keep `insights`, `outreach_angle`, `draft_email` for reference
- Optionally regenerate with V2 pipeline for consistency
- UI should show both legacy and V2 data during transition

### New Records
- Always use V2 pipeline
- Legacy council disabled by default
- Clean, consistent data structure

## Summary

**V2 pipeline achieves**:
- ✅ 83% cost reduction vs. legacy council
- ✅ Comparable or better quality (web-verified)
- ✅ Simpler architecture (2 stages vs. 4+)
- ✅ Clear, explainable logic
- ✅ Fast enough for batch processing

**Default for all new outreach**: DeepSeek → Perplexity → Send
