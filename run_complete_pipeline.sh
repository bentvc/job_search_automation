#!/bin/bash

# COMPLETE HIGH-VOLUME DISCOVERY PIPELINE
# All 7 scrapers for maximum market coverage

echo "🚀 LAUNCHING COMPLETE HIGH-VOLUME PIPELINE"
echo "================================================"
echo "Starting at: $(date)"
echo ""

# Core 4 Quick Wins
echo "📊 [1/7] Multi-Site Job Scraper (LinkedIn + Indeed + ZipRecruiter + Glassdoor)"
python scraper_multisite.py
echo ""

echo "🤖 [2/7] Batch LLM Scoring with MiniMax"
python batch_scorer.py
echo ""

echo "🎯 [3/7] Direct ATS Scraper (Greenhouse + Lever)"
python scraper_ats.py
echo ""

echo "🌟 [4/7] Startup Directory (YC + Wellfound)"
python scraper_startups.py
echo ""

# Bonus 3 Scrapers
echo "💰 [5/7] Rock Health Funding Database"
python scraper_rock_health.py
echo ""

echo "🏥 [6/7] Healthcare-Specific Job Boards (MedReps, HealthcareJobSite, Health eCareers)"
python scraper_niche_boards.py
echo ""

echo "📰 [7/7] RSS Funding News Aggregator (TechCrunch, Fierce Healthcare, etc.)"
python scraper_rss_funding.py
echo ""

echo "✅ COMPLETE PIPELINE FINISHED"
echo "================================================"
echo "Completed at: $(date)"
echo ""

# Comprehensive Results
echo "📈 FINAL DATABASE SNAPSHOT:"
echo "================================================"
sqlite3 data/job_search.db <<EOF
SELECT 
    'Total Jobs:' as metric, 
    COUNT(*) as count 
FROM jobs
UNION ALL
SELECT 
    'New/Unscored:' as metric,
    COUNT(*) as count 
FROM jobs WHERE status='new'
UNION ALL
SELECT 
    'Shortlisted:' as metric,
    COUNT(*) as count 
FROM jobs WHERE status='shortlisted'
UNION ALL
SELECT 
    'Active Companies:' as metric,
    COUNT(*) as count 
FROM companies WHERE monitoring_status='active'
UNION ALL
SELECT 
    'Funding Signals:' as metric,
    COUNT(*) as count 
FROM company_signals WHERE signal_type='funding';
EOF

echo ""
echo "📊 JOB SOURCES BREAKDOWN:"
sqlite3 data/job_search.db "SELECT source, COUNT(*) as count FROM jobs GROUP BY source ORDER BY count DESC;"

echo ""
echo "🔄 Restarting Streamlit Dashboard..."
pkill -f streamlit
sleep 2
nohup streamlit run ui_streamlit.py --server.port 8501 --server.address 0.0.0.0 > streamlit.log 2>&1 &

echo ""
echo "✅ Dashboard live at http://localhost:8501"
echo "================================================"
