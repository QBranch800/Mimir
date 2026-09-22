import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEWSAPI_KEY")

URL = "https://newsapi.org/v2/everything"
SEARCH_TERMS = [
    "sanctions", "tariffs", "trade war", "ceasefire", "summit", "diplomacy", "election",
    "coup", "insurgency", "sovereignty", "annexation", "embargo", "NATO", "alliance",
    "sovereign debt", "currency crisis", "energy security", "oil supply", "gas pipeline",
    "shipping lanes", "chokepoint", "blockade", "military escalation", "troop mobilization",
    "border dispute", "referendum", "regime change", "sovereign default", "capital controls",
    "export controls", "supply chain", "critical minerals", "semiconductor export restrictions",
    "proxy conflict", "peace talks", "arms deal", "nuclear negotiations", "non-proliferation",
    "war crimes", "refugee crisis", "humanitarian corridor", "martial law",
    "coalition government", "secession", "territorial dispute", "maritime dispute",
    "airspace violation", "cyberattack", "espionage", "extradition", "sovereign wealth fund",
    "foreign investment restrictions", "decoupling", "multilateralism", "G7", "G20",
    "UN Security Council", "veto", "sanctions relief", "trade deficit", "currency devaluation",
    "credit rating downgrade", "geopolitical risk premium", "safe haven", "flight to quality",
    "commodity shock", "grain exports", "food security", "drought diplomacy", "water rights",
    "strait", "canal transit",
    "military strike", "oil embargo", "nuclear talks",
]
TERMS_PER_QUERY = 20  # NewsAPI's q parameter has a ~500 character limit
LOOKBACK_DAYS = 2
MAX_ATTEMPTS = 4


def fetch_articles(terms):
    query = " OR ".join(f'"{term}"' for term in terms)
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    params = {
        "q": query,
        "language": "en",
        "from": since,
        "sortBy": "publishedAt",
        "pageSize": 100,
        "apiKey": API_KEY,
    }
    for attempt in range(MAX_ATTEMPTS):
        response = requests.get(URL, params=params, timeout=20)
        data = response.json()
        if data.get("status") == "ok":
            return data["articles"]
        if response.status_code in (429, 426) and attempt < MAX_ATTEMPTS - 1:
            wait = 15 * (attempt + 1)
            print(f"NewsAPI rate limited ({data.get('code')}), retrying in {wait}s...")
            time.sleep(wait)
            continue
        print(f"NewsAPI error: {data.get('code')} {data.get('message')}")
        return None
    return None


unique = {}
for start in range(0, len(SEARCH_TERMS), TERMS_PER_QUERY):
    terms = SEARCH_TERMS[start:start + TERMS_PER_QUERY]
    print(f"Fetching geopolitics from NewsAPI: {', '.join(terms[:3])}, ...")
    items = fetch_articles(terms)
    if items is None:
        print("That group failed, skipping it.")
        continue
    for item in items:
        if item.get("title") in (None, "[Removed]") or not item.get("url"):
            continue
        unique.setdefault(item["url"], item)
    time.sleep(2)

if not unique:
    raise SystemExit("No NewsAPI results, so newsapi_results.json was left untouched.")

articles = []
for item in unique.values():
    articles.append({
        "title": item["title"],
        "url": item["url"],
        "source": item["source"]["name"],
        "time_published": item["publishedAt"].replace("-", "").replace(":", "").rstrip("Z"),
        "summary": item.get("description") or "",
        "banner_image": item.get("urlToImage") or "",
    })

with open("newsapi_results.json", "w") as f:
    json.dump({"geopolitics": articles}, f, indent=2)
print(f"Saved {len(articles)} articles to newsapi_results.json")
