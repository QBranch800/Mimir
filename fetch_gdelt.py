import json
import re
import time
import requests

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
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
TERMS_PER_QUERY = 8
RECORDS_PER_QUERY = 50
MAX_ATTEMPTS = 5


def clean_title(title):
    return re.sub(r"\s+([,.;:?!)])", r"\1", title).strip()


def fetch_articles(terms):
    query = " OR ".join(f'"{term}"' for term in terms)
    params = {
        "query": f"({query}) sourcelang:english",
        "mode": "artlist",
        "format": "json",
        "maxrecords": RECORDS_PER_QUERY,
        "timespan": "1d",
        "sort": "hybridrel",
    }
    for attempt in range(MAX_ATTEMPTS):
        response = requests.get(URL, params=params, timeout=30)
        if response.status_code == 200:
            try:
                return response.json().get("articles", [])
            except ValueError:
                print(f"GDELT did not return JSON: {response.text[:100]}")
                return None
        wait = 10 * (attempt + 1)
        print(f"GDELT returned {response.status_code}, retrying in {wait}s...")
        time.sleep(wait)
    return None


unique = {}
consecutive_failures = 0
for start in range(0, len(SEARCH_TERMS), TERMS_PER_QUERY):
    terms = SEARCH_TERMS[start:start + TERMS_PER_QUERY]
    print(f"Fetching geopolitics from GDELT: {', '.join(terms[:3])}, ...")
    items = fetch_articles(terms)
    if items is None:
        print(f"That group failed, skipping it: {terms}")
        consecutive_failures += 1
        if consecutive_failures >= 2:
            print("2 groups failed in a row, stopping instead of hammering GDELT further.")
            break
        continue
    consecutive_failures = 0
    for item in items:
        unique.setdefault(item["url"], item)
    time.sleep(20)

if not unique:
    raise SystemExit("No GDELT results, so gdelt_results.json was left untouched.")

articles = []
for item in unique.values():
    articles.append({
        "title": clean_title(item["title"]),
        "url": item["url"],
        "source": item["domain"],
        "time_published": item["seendate"].rstrip("Z"),
        "summary": "",
        "banner_image": item.get("socialimage") or "",
    })

with open("gdelt_results.json", "w") as f:
    json.dump({"geopolitics": articles}, f, indent=2)
print(f"Saved {len(articles)} articles to gdelt_results.json")
