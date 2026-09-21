import difflib
import json
import os
import re

BLOCKED_SOURCES = {"MarketBeat", "CBIZ"}
BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\b[\d,]+ shares\b", re.I),
    re.compile(r"\b(takes?|buys?|acquires?|sells?)\b.*\b(position|stake|shares)\b", re.I),
    re.compile(r"\bstock holdings\b", re.I),
    re.compile(r"\b(average|consensus) (rating|recommendation)\b", re.I),
]

# GDELT indexes thousands of outlets, so only geopolitics articles from these are kept
ALLOWED_GEOPOLITICS_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "aljazeera.com",
    "cnbc.com", "bloomberg.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "economist.com", "politico.com", "axios.com", "cnn.com", "npr.org",
    "dw.com", "france24.com", "scmp.com", "thehindu.com", "straitstimes.com",
    "japantimes.co.jp", "channelnewsasia.com", "foreignpolicy.com", "marketwatch.com",
    "barrons.com",
}
SIMILARITY_THRESHOLD = 0.8

with open("results.json") as f:
    results = json.load(f)

if os.path.exists("gdelt_results.json"):
    with open("gdelt_results.json") as f:
        results.update(json.load(f))

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


def is_allowed_domain(source):
    return any(source == d or source.endswith("." + d) for d in ALLOWED_GEOPOLITICS_DOMAINS)


kept = []
kept_keys = []
not_allowed = 0
for article in unique.values():
    if article["source"] in BLOCKED_SOURCES:
        continue
    if any(p.search(article["title"]) for p in BLOCKED_TITLE_PATTERNS):
        continue
    if article["topic"] == "geopolitics" and not is_allowed_domain(article["source"]):
        not_allowed += 1
        continue

    key = normalize_title(article["title"])
    match = None
    for i, other_key in enumerate(kept_keys):
        if difflib.SequenceMatcher(None, key, other_key).ratio() >= SIMILARITY_THRESHOLD:
            match = kept[i]
            break

    if match:
        match["coverage_count"] += 1
        match["also_covered_by"].append(article["source"])
        continue

    article["coverage_count"] = 1
    article["also_covered_by"] = []
    kept.append(article)
    kept_keys.append(key)

total = sum(len(articles) for articles in results.values())
print(f"{total} fetched -> {len(unique)} after URL dedupe -> {len(kept)} after filters and title dedupe")
print(f"{not_allowed} geopolitics articles dropped because their source is not on the allowlist")
multi = sum(1 for a in kept if a["coverage_count"] > 1)
print(f"{multi} stories were covered by more than one outlet")

with open("filtered.json", "w") as f:
    json.dump(kept, f, indent=2)
