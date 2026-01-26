import requests
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv('APOLLO_API_KEY')

def test_api_search():
    url = "https://api.apollo.io/v1/mixed_people/api_search" # Correct endpoint
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": API_KEY
    }
    
    print(f"Testing {url}...")
    
    # 1. Resolve Lensa
    org_resp = requests.post("https://api.apollo.io/v1/organizations/search", 
                           json={"q_organization_name": "Lensa"}, headers=headers)
    org_data = org_resp.json()
    lensa = org_data['organizations'][0]
    org_id = lensa.get('id')
    domain = "lensa.com"
    
    # Test 1: By Org ID (List)
    print("\n--- Test 1: organization_ids (List) ---")
    payload_1 = {
        "organization_ids": [org_id],
        "page": 1
    }
    resp = requests.post(url, json=payload_1, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        people = resp.json().get('people', [])
        print(f"Found: {len(people)}")
        if people: print(f"Sample: {people[0]['name']}")
    else:
        print(resp.text)

    # Test 2: By Domain (String)
    print("\n--- Test 2: q_organization_domains (String) ---")
    payload_2 = {
        "q_organization_domains": domain,
        "page": 1
    }
    resp = requests.post(url, json=payload_2, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        people = resp.json().get('people', [])
        print(f"Found: {len(people)}")
        if people: print(f"Sample: {people[0]['name']}")

    # Test 3: With Titles (String or List?)
    print("\n--- Test 3: person_titles (List) ---")
    payload_3 = {
        "q_organization_domains": domain,
        "person_titles": ["Sales"],
        "page": 1
    }
    resp = requests.post(url, json=payload_3, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        people = resp.json().get('people', [])
        print(f"Found: {len(people)}")
    else:
        print(resp.text)

if __name__ == "__main__":
    test_api_search()
