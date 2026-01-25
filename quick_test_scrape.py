#!/usr/bin/env python3
"""
Quick Test Scraper - Returns results fast for pipeline testing

Usage:
    python3 quick_test_scrape.py --fast     # 30-60s, 5 results
    python3 quick_test_scrape.py --quick    # 1-2min, 20 results (default)
    python3 quick_test_scrape.py --medium   # 3-5min, 50 results
    python3 quick_test_scrape.py --full     # 10-15min, 100 results
"""
import logging
from jobspy import scrape_jobs
import pandas as pd
from datetime import datetime
import argparse
import sys
import os

# Add parent directory to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion import upsert_scraped_jobs

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Test configurations
CONFIGS = {
    'fast': {
        'sites': ['indeed'],
        'hours_old': 6,
        'results_wanted': 5,
        'description': 'Fastest - Minimal results for smoke testing'
    },
    'quick': {
        'sites': ['linkedin', 'indeed'],
        'hours_old': 24,
        'results_wanted': 20,
        'description': 'Quick - Small sample for feature testing'
    },
    'medium': {
        'sites': ['linkedin', 'indeed', 'zip_recruiter'],
        'hours_old': 72,
        'results_wanted': 50,
        'description': 'Medium - Good coverage for calibration'
    },
    'full': {
        'sites': ['indeed', 'linkedin', 'zip_recruiter', 'glassdoor', 'google'],
        'hours_old': 168,
        'results_wanted': 100,
        'description': 'Full - Production-like data'
    }
}

def quick_test_scrape(mode='quick'):
    """
    Fast scrape for testing
    
    Args:
        mode: 'fast', 'quick', 'medium', or 'full'
    """
    config = CONFIGS.get(mode, CONFIGS['quick'])
    
    print("="*80)
    print(f"TEST SCRAPE - {config['description']}")
    print("="*80)
    
    # Focused queries for executive profile
    queries = [
        "VP Revenue Operations healthcare",
        "Chief Revenue Officer healthtech"
    ]
    
    sites = config['sites']
    hours_old = config['hours_old']
    results_wanted = config['results_wanted']
    
    logger.info(f"Queries: {queries}")
    logger.info(f"Sites: {', '.join(sites)}")
    logger.info(f"Timeframe: Last {hours_old} hours")
    logger.info(f"Target Total Results: {results_wanted}")
    logger.info("")
    
    start_time = datetime.now()
    all_jobs_list = []
    
    try:
        results_per_query = results_wanted // len(queries)
        if results_per_query < 5: results_per_query = 5

        for query in queries:
            logger.info(f"🔍 Searching for: {query}...")
            jobs_df = scrape_jobs(
                site_name=sites,
                search_term=query,
                location="United States",
                results_wanted=results_per_query,
                hours_old=hours_old,
                country_indeed='USA',
                linkedin_fetch_description=True
            )
            if jobs_df is not None and not jobs_df.empty:
                logger.info(f"✅ Found {len(jobs_df)} jobs for '{query}'")
                all_jobs_list.append(jobs_df)
            else:
                logger.info(f"⚠️ No jobs found for '{query}'")

        if not all_jobs_list:
            print("\n⚠️ No jobs found across all queries.")
            return None

        combined_df = pd.concat(all_jobs_list, ignore_index=True)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"\n✅ SUCCESS - Found {len(combined_df)} total jobs in {elapsed:.1f}s")
        
        # Ingest into DB
        new_count = upsert_scraped_jobs(combined_df, source=f"quick_test_{mode}")
        
        print(f"📊 Database Ingestion Result: {new_count} new entries.")

        print("\nSample Results:")
        print("-" * 80)
        for idx, row in combined_df.head(5).iterrows():
            print(f"\n{idx+1}. {row.get('title', 'N/A')}")
            print(f"   Company: {row.get('company', 'N/A')}")
            print(f"   Location: {row.get('location', 'N/A')}")
            print(f"   Site: {row.get('site', 'N/A')}")
            
        # Save to CSV for inspection
        output_file = f"test_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        combined_df.to_csv(output_file, index=False)
        print(f"\n💾 Full results saved to: {output_file}")
        
        return combined_df
            
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n❌ FAILED after {elapsed:.1f}s")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Quick scrape for testing')
    parser.add_argument('--fast', action='store_true', help='Fastest mode (5 results, 30-60s)')
    parser.add_argument('--quick', action='store_true', help='Quick mode (20 results, 1-2min) [default]')
    parser.add_argument('--medium', action='store_true', help='Medium mode (50 results, 3-5min)')
    parser.add_argument('--full', action='store_true', help='Full mode (100 results, 10-15min)')
    
    args = parser.parse_args()
    
    # Determine mode
    if args.fast:
        mode = 'fast'
    elif args.medium:
        mode = 'medium'
    elif args.full:
        mode = 'full'
    else:
        mode = 'quick'  # default
    
    print(f"\nStarting {mode.upper()} test scrape...")
    print(f"Expected time: {CONFIGS[mode]['description'].split('for')[0].strip()}\n")
    
    results = quick_test_scrape(mode)
    
    print("\n" + "="*80)
    if results is not None and len(results) > 0:
        print("✅ READY FOR TESTING")
        print(f"Total jobs collected: {len(results)}")
        print("You can now run scoring or the pipeline on these test jobs.")
    else:
        print("⚠️ NO RESULTS - Try broader query or longer timeframe")
    print("="*80)
