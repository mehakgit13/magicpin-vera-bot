import json
import requests

BASE = "http://localhost:8080"
print(requests.get(BASE + "/v1/healthz", timeout=5).json())
print(requests.get(BASE + "/v1/metadata", timeout=5).json())
