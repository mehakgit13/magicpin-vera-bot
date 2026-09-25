import json
from pathlib import Path
import requests

BASE_URL = "http://localhost:8080"
ROOT = Path("expanded")

counts = {
    "category": 0,
    "merchant": 0,
    "customer": 0,
}

def post_context(scope, context_id, payload):
    response = requests.post(
        f"{BASE_URL}/v1/context",
        json={
            "scope": scope,
            "context_id": context_id,
            "version": 1,
            "payload": payload,
            "delivered_at": "2026-05-05T09:00:00Z",
        },
        timeout=10,
    )

    print(
        f"{scope:8} {context_id:50} "
        f"{response.status_code}"
    )

    if response.status_code not in (200, 201):
        print(response.text)
        raise SystemExit(1)

    counts[scope] += 1


for path in sorted((ROOT / "categories").glob("*.json")):
    post_context(
        "category",
        path.stem,
        json.loads(path.read_text(encoding="utf-8")),
    )

for path in sorted((ROOT / "merchants").glob("*.json")):
    post_context(
        "merchant",
        path.stem,
        json.loads(path.read_text(encoding="utf-8")),
    )

for path in sorted((ROOT / "customers").glob("*.json")):
    post_context(
        "customer",
        path.stem,
        json.loads(path.read_text(encoding="utf-8")),
    )

print("\nWarmup loaded:")
print(json.dumps(counts, indent=2))
print(f"Total contexts: {sum(counts.values())}")