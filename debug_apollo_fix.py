import requests
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv('APOLLO_API_KEY')

def test_people_search_fix():
    url = "https://api.apollo.io/v1/people/search"  # Try non-mixed endpoint
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": API_KEY
    }
    
    # 1. Resolve Org Info for Lensa first
    print("--- Resolving Lensa ---")
    org_resp = requests.post("https://api.apollo.io/v1/organizations/search", 
                           json={"q_organization_name": "Lensa"}, headers=headers)
    org_data = org_resp.json()
    lensa = org_data['organizations'][0]
    org_id = lensa.get('id')
    domain = lensa.get('primary_domain')
    print(f"Lensa Found: ID={org_id}, Domain={domain}")
    
    # Test A: people/search with organization_ids (List)
    print("\n--- Test A: people/search with organization_ids as LIST ---")
    payload_a = {
        "organization_ids": [org_id],
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url, json=payload_a, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Results: {len(resp.json().get('people', []))}")
        if resp.json().get('people'):
             print(f"Sample: {resp.json()['people'][0]['name']}")
    else:
        print(resp.text)

    # Test B: mixed_people/search with q_organization_domains as LIST
    print("\n--- Test B: mixed_people/search with q_organization_domains as LIST ---")
    url_mixed = "https://api.apollo.io/v1/mixed_people/search"
    payload_b = {
        "q_organization_domains": [domain], # Wrapped in list
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url_mixed, json=payload_b, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text)
    else:
        print(f"Results: {len(resp.json().get('people', []))}")

    # Test C: mixed_people/search with q_organization_domains as STRING
    print("\n--- Test C: mixed_people/search with q_organization_domains as STRING ---")
    payload_c = {
        "q_organization_domains": domain, # Just string
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url_mixed, json=payload_c, headers=headers)
    print(f"Status: {resp.status_code}")

if __name__ == "__main__":
    test_people_search_fix()
