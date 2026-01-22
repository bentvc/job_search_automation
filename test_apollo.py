from apollo_client import ApolloClient
import logging
import json

logging.basicConfig(level=logging.INFO)
client = ApolloClient()

print("--- Searching for Organization: GitLab ---")
orgs = client.search_organizations("GitLab")
print(json.dumps(orgs, indent=2))

if orgs:
    domain = orgs[0].get("primary_domain")
    print(f"\n--- Searching for People at: {domain} ---")
    people = client.search_people(domain)
    print(json.dumps(people, indent=2))
