import requests
import logging
import config
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ApolloClient:
    """
    Client for interacting with the Apollo.io API to find decision makers.
    """
    BASE_URL = "https://api.apollo.io/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.APOLLO_API_KEY
        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
            "Cache-Control": "no-cache"
        }

    def search_organizations(self, company_name: str) -> List[Dict[str, Any]]:
        """
        Search for an organization by name to find its domain.
        """
        if not self.api_key or "your_" in self.api_key:
            return []

        endpoint = f"{self.BASE_URL}/organizations/search"
        payload = {
            "q_organization_name": company_name,
            "page": 1,
            "per_page": 3
        }

        try:
            response = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                orgs = data.get("organizations", [])
                logger.info(f"Apollo found {len(orgs)} potential companies for '{company_name}'")
                return orgs
            else:
                logger.error(f"Apollo org search failed: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Apollo org search error: {e}")
        return []

    def search_people(self, company_domain: str, titles: List[str] = None) -> List[Dict[str, Any]]:
        """
        Search for people with specific titles at a company domain.
        """
        if not self.api_key or "your_" in self.api_key:
            return []

        endpoint = f"{self.BASE_URL}/mixed_people/api_search"
        
        if not titles:
            titles = config.APOLLO_TARGET_TITLES

        payload = {
            "q_organization_domains": company_domain,
            "person_titles": titles,
            "page": 1,
            "per_page": 10
        }

        try:
            response = requests.post(endpoint, json=payload, headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                people = data.get("people", [])
                logger.info(f"Apollo found {len(people)} contacts for {company_domain}")
                return people
            else:
                logger.error(f"Apollo search failed: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Apollo request error: {e}")
            return []

    def enrich_organization(self, domain: str) -> Dict[str, Any]:
        """
        Get detailed company data from Apollo.
        """
        if not self.api_key or "your_" in self.api_key:
            return {}

        endpoint = f"{self.BASE_URL}/organizations/enrich"
        params = {
            "domain": domain
        }

        try:
            response = requests.get(endpoint, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("organization", {})
        except Exception as e:
            logger.error(f"Apollo enrichment error: {e}")
        return {}
