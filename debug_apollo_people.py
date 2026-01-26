import requests
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv('APOLLO_API_KEY')

def test_people_search():
    url = "https://api.apollo.io/v1/mixed_people/search" # Official endpoint
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
    orgs = org_data.get('organizations', [])
    if not orgs:
        print("Lensa not found!")
        return
        
    lensa = orgs[0]
    org_id = lensa.get('id')
    domain = lensa.get('primary_domain') or lensa.get('domain')
    print(f"Lensa Found: ID={org_id}, Domain={domain}")
    
    # 2. Search People via Domain (No Titles)
    print("\n--- Test 2: Search via Domain (No Titles) ---")
    payload_domain = {
        "q_organization_domains": domain,
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url, json=payload_domain, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Results: {len(resp.json().get('people', []))}")
    if resp.json().get('people'):
        print(f"Sample: {resp.json()['people'][0]['name']} - {resp.json()['people'][0]['email']}")

    # 3. Search via ID (No Titles)
    print("\n--- Test 3: Search via Org ID (No Titles) ---")
    payload_id = {
        "organization_ids": [org_id],
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url, json=payload_id, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Results: {len(resp.json().get('people', []))}")

    # 4. Search via Titles (Broad)
    print("\n--- Test 4: Search via Domain + Titles ['Sales', 'CEO'] ---")
    payload_titles = {
        "q_organization_domains": domain,
        "person_titles": ["Sales", "CEO"],
        "page": 1,
        "per_page": 3
    }
    resp = requests.post(url, json=payload_titles, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Results: {len(resp.json().get('people', []))}")

if __name__ == "__main__":
    test_people_search()
