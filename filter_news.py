import datetime
import difflib
import json
import os
import re
from urllib.parse import urlparse

import categories
import paths

# Sources that only ever produce algorithmic single-stock filler or SEO content farming.
# Each was checked against a day of scored output: none produced a single useful story.
BLOCKED_SOURCES = {
    "MarketBeat", "CBIZ", "AD HOC NEWS", "Kalkine Media",
    "Stock Titan", "Insider Monkey", "Pluang", "scanx.trade",
    "Simply Wall St", "Simply Wall Street",
}
BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\b[\d,]+ shares\b", re.I),
    re.compile(r"\b(takes?|buys?|acquires?|sells?)\b.*\b(position|stake|shares)\b", re.I),
    re.compile(r"\bstock holdings\b", re.I),
    re.compile(r"\b(average|consensus) (rating|recommendation)\b", re.I),
    # content-farm question headlines, e.g. "What Is Driving Attention to X (NASDAQ:Y)?"
    re.compile(r"^(what|why|could|is|are|has|does|do)\b.{0,80}\([A-Z]{2,6}:[A-Z.]+\)", re.I),
    # algorithmic stock-movement filler, e.g. "X stock edges higher after ..."
    re.compile(r"\bstock (edges|gains?|holds?|slips?|trades?|heads?|dips?|climbs?)\b", re.I),
    # the same thing written more excitedly, e.g. "Why Is X Stock Surging Premarket?"
    re.compile(r"\bstocks? (is |are )?(surg|soar|jump|plung|tumbl|ralli|rall|sink|spik|"
               r"crater|slump|skyrocket)\w*", re.I),
    re.compile(r"\b(pre-?market|after-?hours) (trading|move|gains?|losses?|today)\b", re.I),
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

# Geopolitics articles are kept only from these outlets
ALLOWED_GEOPOLITICS_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "aljazeera.com",
    "cnbc.com", "bloomberg.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "economist.com", "politico.com", "axios.com", "cnn.com", "npr.org",
    "dw.com", "france24.com", "scmp.com", "thehindu.com", "straitstimes.com",
    "japantimes.co.jp", "channelnewsasia.com", "foreignpolicy.com", "marketwatch.com",
    "barrons.com",
}
SIMILARITY_THRESHOLD = 0.8

# A daily briefing: anything older than this is not today's news. It also means a source
# whose fetch failed cannot leak its last, stale results into a fresh briefing.
MAX_AGE_HOURS = 36

# Read in this order, because when the same story arrives from several places the first
# copy is the one kept: RSS is fresh and from chosen outlets, NewsAPI's free tier runs a
# day late, and Alpha Vantage is mostly stock filler. Every source is optional.
SOURCE_FILES = ["rss_results.json", "results.json", "newsapi_results.json"]

results = {}
for name in SOURCE_FILES:
    if not os.path.exists(paths.data(name)):
        continue
    with open(paths.data(name)) as f:
        for topic, articles in json.load(f).items():
            results.setdefault(topic, []).extend(articles)

if not results:
    raise SystemExit("No fetched news to filter. Run the fetch steps first.")

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


def age_hours(article, now):
    """Hours since publication, or None when the date cannot be read."""
    stamp = (article.get("time_published") or "").rstrip("Z")
    try:
        when = datetime.datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return (now - when.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600


def is_allowed_domain(domain):
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_GEOPOLITICS_DOMAINS)


now = datetime.datetime.now(datetime.timezone.utc)
kept = []
kept_keys = []
dropped = {"too old": 0, "blocked source": 0, "stock filler title": 0, "market roundup": 0,
           "outlet not on allowlist": 0, "off topic": 0}
for article in unique.values():
    age = age_hours(article, now)
    if age is not None and age > MAX_AGE_HOURS:
        dropped["too old"] += 1
        continue
    if article["source"] in BLOCKED_SOURCES:
        dropped["blocked source"] += 1
        continue
    if any(p.search(article["title"]) for p in BLOCKED_TITLE_PATTERNS):
        dropped["stock filler title"] += 1
        continue
    if any(p.search(article["title"]) for p in ROUNDUP_TITLE_PATTERNS):
        dropped["market roundup"] += 1
        continue
    # RSS feeds are chosen by hand; only NewsAPI's open-ended geopolitics search needs this
    if (article["topic"] == "geopolitics" and not article.get("trusted")
            and not is_allowed_domain(get_domain(article))):
        dropped["outlet not on allowlist"] += 1
        continue
    # cheap and generous: stops sport, celebrity and lifestyle stories costing a request
    if not categories.is_relevant(article):
        dropped["off topic"] += 1
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
for reason, count in dropped.items():
    if count:
        print(f"  {count:4} dropped: {reason}")
multi = sum(1 for a in kept if a["coverage_count"] > 1)
print(f"{multi} stories were covered by more than one outlet")

with open(paths.data("filtered.json"), "w") as f:
    json.dump(kept, f, indent=2)
