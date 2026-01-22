#!/bin/bash

# QUICK WINS EXECUTION SCRIPT
# Runs all 4 high-volume scrapers in sequence

echo "🚀 LAUNCHING HIGH-VOLUME JOB DISCOVERY PIPELINE"
echo "================================================"
echo ""

# Quick Win #1: Multi-Site JobSpy
echo "📊 [1/4] Multi-Site Job Scraper (LinkedIn + Indeed + ZipRecruiter + Glassdoor)"
python scraper_multisite.py
echo ""

# Quick Win #2: Batch LLM Scoring
echo "🤖 [2/4] Batch LLM Scoring with MiniMax"
python batch_scorer.py
echo ""

# Quick Win #3: Direct ATS Scraping
echo "🎯 [3/4] Direct ATS Scraper (Greenhouse + Lever)"
python scraper_ats.py
echo ""

# Quick Win #4: Startup Universe
echo "🌟 [4/4] Startup Directory (YC + Wellfound)"
python scraper_startups.py
echo ""

echo "✅ PIPELINE COMPLETE"
echo "================================================"
echo ""

# Show results
echo "📈 DATABASE SNAPSHOT:"
sqlite3 data/job_search.db "SELECT 
    (SELECT COUNT(*) FROM jobs WHERE status='new') as new_jobs,
    (SELECT COUNT(*) FROM jobs WHERE status='shortlisted') as shortlisted,
    (SELECT COUNT(*) FROM companies WHERE monitoring_status='active') as active_companies;"

echo ""
echo "🔄 Starting Streamlit Dashboard..."
pkill -f streamlit
nohup streamlit run ui_streamlit.py --server.port 8501 --server.address 0.0.0.0 > streamlit.log 2>&1 &

echo "✅ Dashboard available at http://localhost:8501"
