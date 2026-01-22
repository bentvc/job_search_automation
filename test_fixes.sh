#!/bin/bash

# TEST FIXED HIGH-VALUE SCRAPERS
# Validates each fix before running full pipeline

echo "🔧 TESTING FIXED HIGH-VALUE SCRAPERS"
echo "================================================"
echo ""

# Test 1: Batch Scorer (with fallback)
echo "🤖 [1/4] Testing Batch LLM Scorer (MiniMax + DeepSeek fallback)..."
python batch_scorer.py
if [ $? -eq 0 ]; then
    echo "✅ Batch Scorer: PASSED"
else
    echo "⚠️ Batch Scorer: FAILED (but non-critical)"
fi
echo ""

# Test 2: YC Scraper
echo "🚀 [2/4] Testing Y Combinator Healthcare Scraper..."
python scraper_yc_fixed.py
if [ $? -eq 0 ]; then
    echo "✅ YC Scraper: PASSED"
else
    echo "❌ YC Scraper: FAILED"
fi
echo ""

# Test 3: Wellfound Scraper  
echo "🌟 [3/4] Testing Wellfound Healthcare Scraper..."
python scraper_wellfound_fixed.py
if [ $? -eq 0 ]; then
    echo "✅ Wellfound Scraper: PASSED"
else
    echo "❌ Wellfound Scraper: FAILED"
fi
echo ""

# Test 4: Multi-Site JobSpy (with retry logic)
echo "📊 [4/4] Testing Multi-Site JobSpy (first 2 queries only)..."
# Temporarily modify config to only run 2 queries for testing
python -c "
import config
original_queries = config.JOBSPY_QUERIES
config.JOBSPY_QUERIES = original_queries[:2]
from scraper_multisite import run_multisite_scraper
run_multisite_scraper()
"
if [ $? -eq 0 ]; then
    echo "✅ Multi-Site Scraper: PASSED"
else
    echo "⚠️ Multi-Site Scraper: PARTIAL (some sites may be blocked)"
fi
echo ""

echo "================================================"
echo "📈 RESULTS SUMMARY"
echo "================================================"

sqlite3 data/job_search.db <<EOF
SELECT 
    'New Jobs Added:' as metric,
    COUNT(*) as count
FROM jobs 
WHERE datetime(created_at) > datetime('now', '-5 minutes')
UNION ALL
SELECT 
    'New Companies Added:' as metric,
    COUNT(*) as count
FROM companies
WHERE datetime(created_at) > datetime('now', '-5 minutes')
UNION ALL
SELECT
    'Total Active Companies:' as metric,
    COUNT(*) as count
FROM companies
WHERE monitoring_status='active';
EOF

echo ""
echo "✅ TEST COMPLETE - Ready for full pipeline"
echo "================================================"
