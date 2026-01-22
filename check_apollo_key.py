import requests
import config

url = f"https://api.apollo.io/v1/auth/health?api_key=p0kDAf1eJJua2MIFvNYMyg"
resp = requests.get(url)
print(f"Status: {resp.status_code}")
print(f"Body: {resp.text}")
