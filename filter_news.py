import difflib
import json
import os
import re
from urllib.parse import urlparse

# Sources that only ever produce algorithmic single-stock filler or SEO content farming
BLOCKED_SOURCES = {"MarketBeat", "CBIZ", "AD HOC NEWS", "Kalkine Media"}
BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\b[\d,]+ shares\b", re.I),
    re.compile(r"\b(takes?|buys?|acquires?|sells?)\b.*\b(position|stake|shares)\b", re.I),
    re.compile(r"\bstock holdings\b", re.I),
    re.compile(r"\b(average|consensus) (rating|recommendation)\b", re.I),
    # content-farm question headlines, e.g. "What Is Driving Attention to X (NASDAQ:Y)?"
    re.compile(r"^(what|why|could|is|are|has|does|do)\b.{0,80}\([A-Z]{2,6}:[A-Z.]+\)", re.I),
    # algorithmic stock-movement filler, e.g. "X stock edges higher after ..."
    re.compile(r"\bstock (edges|gains?|holds?|slips?|trades?|heads?|dips?|climbs?)\b", re.I),
]

# Recurring market roundups and previews. These are competing briefings, not discrete events,
# so they crowd out real news even when their content is on topic.
ROUNDUP_TITLE_PATTERNS = [
    re.compile(r"\bdaily open\b", re.I),
    re.compile(r"\bmarkets? brief\b", re.I),
    re.compile(r"\bwhat to expect in markets\b", re.I),
    re.compile(r"\bthis week in\b", re.I),
    re.compile(r"\bweek ahead\b", re.I),
    re.compile(r"\bweekly (recap|roundup|preview|wrap)\b", re.I),
    re.compile(r"\b(opening|closing) bell\b", re.I),
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

for extra_file in ("gdelt_results.json", "newsapi_results.json"):
    if os.path.exists(extra_file):
        with open(extra_file) as f:
            extra = json.load(f)
        for topic, articles in extra.items():
            results.setdefault(topic, []).extend(articles)

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


def get_domain(article):
    netloc = urlparse(article["url"]).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_allowed_domain(domain):
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_GEOPOLITICS_DOMAINS)


kept = []
kept_keys = []
not_allowed = 0
roundups = 0
for article in unique.values():
    if article["source"] in BLOCKED_SOURCES:
        continue
    if any(p.search(article["title"]) for p in BLOCKED_TITLE_PATTERNS):
        continue
    if any(p.search(article["title"]) for p in ROUNDUP_TITLE_PATTERNS):
        roundups += 1
        continue
    if article["topic"] == "geopolitics" and not is_allowed_domain(get_domain(article)):
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
print(f"{roundups} recurring market roundups/previews dropped")
multi = sum(1 for a in kept if a["coverage_count"] > 1)
print(f"{multi} stories were covered by more than one outlet")

with open("filtered.json", "w") as f:
    json.dump(kept, f, indent=2)
