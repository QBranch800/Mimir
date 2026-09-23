import json
import os
import time
import requests
from dotenv import load_dotenv

import paths

# override, so the key saved in the data directory always wins over one that
# happens to be in the environment already
load_dotenv(paths.data(".env"), override=True)

# Refuse to call the API without a key rather than sending a request that is bound to
# be rejected. This makes a first run say plainly what is missing, and makes it obvious
# if a key is somehow coming from somewhere other than the file the person edited.
_key = os.getenv("ALPHA_VANTAGE_API_KEY")
if not _key:
    raise SystemExit(
        "No Alpha Vantage key. Add ALPHA_VANTAGE_API_KEY in Settings, or to "
        + paths.data(".env") + " (free key at alphavantage.co)."
    )
_env_file = paths.data(".env")
_from_file = os.path.exists(_env_file) and any(
    line.strip().startswith("ALPHA_VANTAGE_API_KEY=") for line in open(_env_file))
print(f"Using Alpha Vantage key from "
      f"{_env_file if _from_file else 'the environment, not from a file'} "
      f"(ends ...{_key[-4:]})")
API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

BASE_URL = "https://www.alphavantage.co/query"
TOPICS = ["economy_macro", "economy_monetary", "economy_fiscal", "technology"]
results = {}

for topic in TOPICS:
    print(f"Fetching {topic}...")
    params = {"function": "NEWS_SENTIMENT", "topics": topic, "apikey": API_KEY}
    response = requests.get(BASE_URL, params=params, timeout=10)
    data = response.json()

    if "feed" not in data:
        print(f"No feed for {topic}. API said: {data}")
        continue

    results[topic] = data["feed"]

    for article in data["feed"][:3]:
        print(article["title"])

    time.sleep(2)

with open(paths.data("results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved {len(results)} topics to results.json")
