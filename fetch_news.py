import json
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
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

with open("results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved {len(results)} topics to results.json")
