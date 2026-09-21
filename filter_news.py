import json
import re

BLOCKED_SOURCES = {"MarketBeat", "CBIZ"}
BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\b[\d,]+ shares\b", re.I),
    re.compile(r"\b(takes?|buys?|acquires?|sells?)\b.*\b(position|stake|shares)\b", re.I),
    re.compile(r"\bstock holdings\b", re.I),
    re.compile(r"\b(average|consensus) (rating|recommendation)\b", re.I),
]

with open("results.json") as f:
    results = json.load(f)

unique = {}
for topic, articles in results.items():
    for article in articles:
        if article["url"] not in unique:
            article["topic"] = topic
            unique[article["url"]] = article

kept = []
for article in unique.values():
    if article["source"] in BLOCKED_SOURCES:
        continue
    if any(p.search(article["title"]) for p in BLOCKED_TITLE_PATTERNS):
        continue
    kept.append(article)

total = sum(len(articles) for articles in results.values())
print(f"{total} fetched -> {len(unique)} after dedupe -> {len(kept)} after filters")

with open("filtered.json", "w") as f:
    json.dump(kept, f, indent=2)
