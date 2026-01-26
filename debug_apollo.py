import requests
import os
from dotenv import load_dotenv
import json

load_dotenv(override=True)

API_KEY = os.getenv('APOLLO_API_KEY')
print(f"Loaded Key: {API_KEY[:4]}...{API_KEY[-4:] if API_KEY else 'NONE'}")

def test_search():
    url = "https://api.apollo.io/v1/organizations/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": API_KEY
    }
    payload = {
        "q_organization_name": "Evolent Health",
        "page": 1,
        "per_page": 5
    }
    
    print("\nAttempting Search for 'Evolent Health'...")
    try:
        resp = requests.post(url, json=payload, headers=headers)
        print(f"Status: {resp.status_code}")
        try:
            print("Response JSON:")
            print(json.dumps(resp.json(), indent=2)[:500] + "...") # Print first 500 chars
        except:
            print("Response Text:", resp.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search()
