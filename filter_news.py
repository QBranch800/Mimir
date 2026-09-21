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

def normalize_title(title):
    title = title.lower()
    title = re.sub(r"\s+by (reuters|investing\.com|bloomberg)$", "", title)
    title = re.sub(r"[^a-z0-9 ]", "", title)
    return " ".join(title.split())


kept = []
seen_titles = set()
for article in unique.values():
    if article["source"] in BLOCKED_SOURCES:
        continue
    if any(p.search(article["title"]) for p in BLOCKED_TITLE_PATTERNS):
        continue
    title_key = normalize_title(article["title"])
    if title_key in seen_titles:
        continue
    seen_titles.add(title_key)
    kept.append(article)

total = sum(len(articles) for articles in results.values())
print(f"{total} fetched -> {len(unique)} after URL dedupe -> {len(kept)} after filters and title dedupe")

with open("filtered.json", "w") as f:
    json.dump(kept, f, indent=2)
