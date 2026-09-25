"""Fetch US fiscal policy, US macro data and tech and AI headlines from Alpha Vantage.

This is the source for those three categories. Most of what it returns is stock filler
from content farms, so filter_news.py keeps only the few stories that use their
category's own words.
"""

import datetime
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
# Alpha Vantage topic -> the category it feeds
TOPICS = {
    "economy_fiscal": "us_fiscal_policy",
    "economy_macro": "us_macro_data",
    "technology": "tech_and_ai",
}
# The whole day, not just the latest 50. Asking for the latest returned an hour or two
# of overnight content-farm output: on 09-24 not one of the 150 fiscal, macro and tech
# articles was useful. The free plan allows 25 requests a day; a run uses three.
LOOKBACK_HOURS = 36
since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=LOOKBACK_HOURS)
results = {}

for topic, category in TOPICS.items():
    print(f"Fetching {topic}...")
    params = {"function": "NEWS_SENTIMENT", "topics": topic, "sort": "RELEVANCE",
              "time_from": since.strftime("%Y%m%dT%H%M"), "limit": 1000, "apikey": API_KEY}
    response = requests.get(BASE_URL, params=params, timeout=30)
    data = response.json()

    if "feed" not in data:
        print(f"No feed for {topic}. API said: {data}")
        continue

    results[category] = data["feed"]
    print(f"  {len(data['feed'])} articles")
    time.sleep(2)

if not results:
    raise SystemExit("Alpha Vantage returned nothing, so results.json was left untouched.")

with open(paths.data("results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved {sum(len(v) for v in results.values())} articles to results.json")
