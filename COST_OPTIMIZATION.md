# COST OPTIMIZATION & MODEL SELECTION GUIDE

## 🚨 CRITICAL: Start Cheap, Scale Up Only If Needed

**DEFAULT RULE**: Always use the cheapest model that produces acceptable results. Only upgrade if quality is insufficient after testing.

## Cost Tiers (per 1M tokens)

### Tier 1: Ultra-Cheap (Default Starting Point)
- **MiniMax 2.1**: $0.005 - Primary choice for all tasks
- **DeepSeek V3**: $0.14 - Fallback if MiniMax fails
- **Qwen 2.5 (Ollama)**: FREE - Local inference, no API costs

### Tier 2: Budget (Use if Tier 1 insufficient)
- **Gemini Flash 2.0**: $0.075 - Fast, good quality
- **Gemini Flash 1.5**: $0.15 - Slightly better quality
- **GPT-4o-mini**: $0.15 - Solid fallback

### Tier 3: Premium (⚠️ AVOID UNLESS EXPLICITLY NEEDED)
- **GPT-4o**: $2.50 - Use only for complex reasoning
- **Claude Sonnet 3.5**: $3.00 - Use only for critical writing
- **Claude Opus**: $15.00 - **NEVER USE WITHOUT EXPLICIT APPROVAL**

## Cost Per Outreach (Estimated)

### Current Optimized Stack
- **Wedge Analysis** (MiniMax): $0.001
- **Council Analysis** (MiniMax + Qwen local): $0.002
- **Draft Generation** (MiniMax): $0.003
- **Optional Polish** (Gemini Flash): $0.002
- **Total**: ~$0.008 per outreach

### Previous Stack (Before Fix)
- OpenAI GPT-4 + Anthropic Claude: ~$0.50-1.00 per outreach
- **62x more expensive!**

## Model Selection Rules

### For LLM Tasks (utils.py / call_llm)

**Priority order** (from utils.py):
```python
all_providers = [
    ('minimax', ..., ...),      # Try this FIRST
    ('ollama', ..., ...),        # Try local models SECOND (if available)
    ('deepseek', ..., ...),      # Cheap fallback
    ('google', ..., ...),        # Gemini Flash for specific tasks
    ('openai', ..., ...),        # Only if all above fail
    ('anthropic', ..., ...),     # LAST RESORT
]
```

**Forced provider usage**:
- ✅ `forced_provider="minimax"` - Default for most tasks
- ✅ `forced_provider="ollama"` - For analysis/reasoning (free!)
- ✅ `forced_provider="google"` - For writing tasks (cheap)
- ❌ `forced_provider="anthropic"` - **AVOID unless critical**

### For Specific Use Cases

#### Job Scoring (agent1_job_scraper.py)
- **Primary**: MiniMax 2.1
- **Batch mode**: Process 50+ jobs per call
- **Cost**: ~$0.0001 per job

#### Company Scoring (enhanced_scoring.py)
- **Primary**: Local Qwen via Ollama (free!)
- **Fallback**: MiniMax 2.1
- **Cost**: ~$0.00 (local) or $0.002 (API)

#### Council of Agents (sync_leads.py)
1. **Wedge Identification**: MiniMax (~$0.001)
2. **Strategic Analysis**: Qwen local (~$0.00)
3. **Draft Writing**: MiniMax (~$0.003)
4. **Optional Polish**: Gemini Flash (~$0.002) - only if draft is rough

#### Signal Monitoring (agent2_signal_monitor.py)
- **Primary**: MiniMax 2.1
- **For news summarization**: Qwen local (free)
- **Cost**: ~$0.001 per company

## Testing Protocol

### Before Any Expensive Operation

1. **Test with 1-2 samples** using MiniMax/Qwen
2. **Evaluate quality**:
   - Does it follow instructions?
   - Is the output coherent?
   - Are there hallucinations?
3. **If acceptable**: Continue with cheap models
4. **If poor quality**: Test with Gemini Flash
5. **If still poor**: Ask user before upgrading to premium

### Never Automatically Use Premium Models

```python
# ❌ BAD - Defaults to expensive model
response = call_llm(prompt, model="gpt-4o")

# ❌ BAD - Forces expensive provider
response = call_llm(prompt, forced_provider="anthropic")

# ✅ GOOD - Uses cheap fallback chain
response = call_llm(prompt)

# ✅ GOOD - Explicitly cheap
response = call_llm(prompt, forced_provider="minimax")
```

## Budget Alerts

### Daily Spending Targets
- **Normal operations**: <$1/day
- **Heavy regeneration** (100+ records): <$5/day
- **Alert threshold**: >$10/day
- **STOP immediately**: >$20/day

### Cost Tracking

Monitor usage with:
```bash
# Check recent LLM calls
tail -100 automated_pipeline.log | grep "failed\|succeeded"

# Count API calls by provider
grep -c "Minimax\|OpenAI\|Anthropic" automated_pipeline.log
```

## Ollama Setup (Local Models)

### Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve  # Run in background
```

### Install Recommended Models
```bash
# Primary: Qwen 2.5 32B quantized (reasoning/analysis)
ollama pull qwen2.5:32b-instruct-q4_K_M  # 20GB, good balance

# Alternative: Llama 3.3 70B (if you have GPU)
ollama pull llama3.3:70b-instruct-q4_K_M  # 40GB, better quality

# Lightweight: Qwen 14B (if low on resources)
ollama pull qwen2.5:14b-instruct-q4_K_M  # 9GB, fast
```

### Integration
See `ollama_client.py` for integration with the Council system.

## Emergency Cost Controls

### If you accidentally trigger expensive calls:

```bash
# Kill running processes immediately
pkill -f fix_and_regenerate.py
pkill -f agent1_job_scraper.py
pkill -f sync_leads.py

# Check what's running
ps aux | grep python | grep job_search
```

### If you see premium model calls in logs:

1. **Stop immediately**
2. **Check utils.py** - verify provider priority
3. **Check forced_provider** calls - remove any anthropic/openai forcing
4. **Test with --test flag** before full runs

## Recommended .env Settings

```bash
# Primary (ultra-cheap)
MINIMAX_API_KEY=your_actual_key_here

# Fallbacks (cheap)
DEEPSEEK_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here

# Premium (use sparingly)
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# Disable premium models entirely (optional)
# OPENAI_API_KEY=disabled
# ANTHROPIC_API_KEY=disabled
```

## Summary: Always Ask Yourself

Before running any LLM operation:
1. ✅ Am I using MiniMax/Qwen first?
2. ✅ Have I tested with 1-2 samples?
3. ✅ Is there a batch mode I can use?
4. ❌ Am I forcing expensive providers?
5. ❌ Will this cost more than $1?

**When in doubt: Test cheap first, upgrade only if needed!**
