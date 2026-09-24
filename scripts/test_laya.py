"""Smoke-test the Laya server (reads key from .env, never prints it)."""
import json
import urllib.request
from dotenv import dotenv_values

env = dotenv_values(".env")
base = env["LAYA_BASE_URL"]
key = env["LAYA_API_KEY"]
body = json.dumps({
    "state": {"body": "Card charged $292.36 online, cardholder denies it."},
    "questions": {"is_fraud": {"type": "noul", "instructions": "Is this fraud?"}},
}).encode()
req = urllib.request.Request(
    base + "/v1/systemone", data=body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
)
with urllib.request.urlopen(req, timeout=120) as r:
    d = json.load(r)
print("HTTP OK")
print("answers:", json.dumps(d.get("answers", d), default=str)[:300])
print("usage:", d.get("usage"))
