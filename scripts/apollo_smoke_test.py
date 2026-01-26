
from apollo_client import ApolloClient
import logging
import sys

# Setup logging to stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(message)s')

def test_apollo():
    print("\n--- Starting Apollo Smoke Test ---")
    c = ApolloClient()
    
    # 1. Org Search
    print("\n[1] Search Org 'Gravie'")
    orgs = c.search_organizations("Gravie")
    print(f"Orgs found: {len(orgs)}")
    
    if not orgs:
        print("No orgs found, stopping.")
        return

    org_id = orgs[0].get("id")
    print(f"Using Org ID: {org_id}")

    # 2. People Search
    print(f"\n[2] Search People at Org {org_id}")
    people = c.search_people(organization_ids=[org_id])
    print(f"People found: {len(people)}")

    if not people:
        print("No people found, stopping.")
        return

    pid = people[0].get("id")
    print(f"Using Person ID: {pid}")

    # 3. Fetch (Get)
    print(f"\n[3] Fetch/Unlock Person {pid} (GET)")
    fetched = c.unlock_person_email(pid)
    print(f"Fetch Status: {fetched.get('http_status')}")
    print(f"Fetch Keys: {list(fetched.get('raw_response', {}).keys())}")

    # 4. Reveal (Post Bulk Match)
    print(f"\n[4] Reveal Person {pid} (POST Bulk Match)")
    revealed = c.reveal_person_email(pid)
    print(f"Reveal Status: {revealed.get('http_status')}")
    print(f"Credits: {revealed.get('credits_consumed')}")
    print(f"Reveal Raw Keys: {list(revealed.get('raw_response', {}).keys())}")
    
    if revealed.get('parsed_person'):
        print(f"Match[0] Keys: {list(revealed['parsed_person'].keys())}")
    else:
        print("No match parsed.")

if __name__ == "__main__":
    test_apollo()
