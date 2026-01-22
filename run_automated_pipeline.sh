#!/bin/bash

# AUTOMATED COMPLETE PIPELINE ORCHESTRATION
# Waits for current scraper, then runs all remaining scrapers + scoring + sync

echo "🤖 AUTOMATED PIPELINE ORCHESTRATION"
echo "================================================"
echo "Started at: $(date)"
echo ""

# PHASE 1: Wait for Multi-Site Scraper (already running)
echo "⏳ [Phase 1] Waiting for Multi-Site Scraper to complete..."
echo "   (This is already running in background)"
echo ""

# Check if multisite scraper is still running
while pgrep -f "scraper_multisite.py" > /dev/null; do
    sleep 10
    echo "   Still scraping... ($(date +%H:%M:%S))"
done

echo "✅ Multi-Site Scraper complete!"
echo ""

# PHASE 2: Batch Scoring
echo "🤖 [Phase 2] Batch LLM Scoring (all unscored jobs)..."
python batch_scorer.py
echo ""

# PHASE 3: YC Healthcare Companies
echo "🚀 [Phase 3] Y Combinator Healthcare Scraper..."
python scraper_yc_fixed.py
echo ""

# PHASE 4: Direct ATS Scraping
echo "🎯 [Phase 4] Direct ATS Scraper (Greenhouse + Lever)..."
python scraper_ats.py
echo ""

# PHASE 5: Rock Health Funding
echo "💰 [Phase 5] Rock Health Funding Database..."
python scraper_rock_health.py
echo ""

# PHASE 6: Healthcare Job Boards
echo "🏥 [Phase 6] Healthcare-Specific Job Boards..."
python scraper_niche_boards.py
echo ""

# PHASE 7: RSS Funding Aggregator
echo "📰 [Phase 7] RSS Funding News Aggregator..."
python scraper_rss_funding.py
echo ""

# PHASE 8: Sync Leads & Generate Outreach
echo "🔄 [Phase 8] Syncing Leads & Generating Outreach..."
python sync_leads.py
echo ""

echo "================================================"
echo "🎉 COMPLETE PIPELINE FINISHED"
echo "================================================"
echo "Completed at: $(date)"
echo ""

# Final Statistics
echo "📊 FINAL RESULTS:"
echo "================================================"
sqlite3 data/job_search.db <<EOF
.mode column
.headers on
SELECT 
    'METRIC' as Category,
    'COUNT' as Value
UNION ALL
SELECT 'Total Jobs', CAST(COUNT(*) AS TEXT) FROM jobs
UNION ALL
SELECT 'New/Unscored', CAST(COUNT(*) AS TEXT) FROM jobs WHERE status='new'
UNION ALL  
SELECT 'Shortlisted', CAST(COUNT(*) AS TEXT) FROM jobs WHERE status='shortlisted'
UNION ALL
SELECT 'Active Companies', CAST(COUNT(*) AS TEXT) FROM companies WHERE monitoring_status='active'
UNION ALL
SELECT 'Funding Signals', CAST(COUNT(*) AS TEXT) FROM company_signals WHERE signal_type='funding'
UNION ALL
SELECT 'Queued Outreach', CAST(COUNT(*) AS TEXT) FROM proactive_outreach WHERE status='queued';
EOF

echo ""
echo "📈 JOB SOURCES:"
sqlite3 data/job_search.db "SELECT source, COUNT(*) as count FROM jobs GROUP BY source ORDER BY count DESC LIMIT 10;"

echo ""
echo "🔄 Restarting Streamlit Dashboard..."
pkill -f streamlit
sleep 2
nohup streamlit run ui_streamlit.py --server.port 8501 --server.address 0.0.0.0 > streamlit.log 2>&1 &

echo ""
echo "✅ All systems operational!"
echo "📊 Dashboard: http://localhost:8501"
echo "================================================"
