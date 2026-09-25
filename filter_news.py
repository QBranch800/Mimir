"""Cut the fetched news down to the few stories per category worth a Gemini request.

Every story that reaches Gemini costs part of a request from a free allowance of 20 a
day, so this is strict on purpose. A story has to be recent, not filler, and plainly
about a category its source was chosen for. Then each category keeps only its
MAX_PER_CATEGORY biggest stories, judged by how many outlets are carrying them.
"""

import collections
import datetime
import difflib
import json
import os
import re

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
    # syndicated stock-picking, which aggregators republish under a dozen names, so it
    # looks widely covered when it is one piece of filler
    re.compile(r"\bwhich .{0,40}\bis (a|the) better buy\b", re.I),
    re.compile(r"\bshares are (falling|rising|soaring|plunging|trading)\b", re.I),
    re.compile(r"\b(opened|moved|closed) (up|down) by [\d.]+%", re.I),
    re.compile(r"\bstock price, news, quote\b", re.I),
    re.compile(r"\bzacks\b", re.I),
    re.compile(r"\bmarket chatter\b", re.I),
    # law firms advertising for class action plaintiffs
    re.compile(r"\binvestigating (allegations|claims)\b|\bclass action\b|\bshareholder (alert|rights)\b", re.I),
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

SIMILARITY_THRESHOLD = 0.8

# A daily briefing: anything older than this is not today's news. It also means a source
# whose fetch failed cannot leak its last, stale results into a fresh briefing.
MAX_AGE_HOURS = 36

# The most any category sends to Gemini. Five categories of ten is one request.
MAX_PER_CATEGORY = 10

# The file each source writes, and the name categories.SOURCE knows it by. Every source
# is optional: if one fails, the run carries on with the others.
SOURCE_FILES = {
    "rss_results.json": "rss",
    "results.json": "alpha_vantage",
    "gdelt_results.json": "gdelt",
}

unique = {}
total = 0
for name, feed in SOURCE_FILES.items():
    if not os.path.exists(paths.data(name)):
        continue
    with open(paths.data(name)) as f:
        for hint, articles in json.load(f).items():
            for article in articles:
                total += 1
                if article["url"] not in unique:
                    article["feed"] = feed
                    article["topic"] = hint     # the category it was fetched for
                    unique[article["url"]] = article

if not unique:
    raise SystemExit("No fetched news to filter. Run the fetch steps first.")


def normalize_title(title):
    title = title.lower()
    title = re.sub(r"\s+by (reuters|investing\.com|bloomberg)$", "", title)
    title = re.sub(r"[^a-z0-9 ]", "", title)
    return " ".join(title.split())


def age_hours(article, now):
    """Hours since publication, or None when the date cannot be read."""
    stamp = (article.get("time_published") or "").rstrip("Z")
    try:
        when = datetime.datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return (now - when.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600


def category_for(article):
    """The category the story is plainly about, among those its source covers, or None.

    The one it was fetched for is tried first, but an Alpha Vantage "fiscal" story that
    is really a jobs report can still count as macro data.
    """
    options = categories.categories_of(article["feed"])
    options.sort(key=lambda c: c != article["topic"])
    return next((c for c in options if categories.on_topic(article, c)), None)


def story_words(title):
    """The capitalised words of a headline: the names that say which story it is."""
    return {w.lower() for w in re.findall(r"\b[A-Z][A-Za-z0-9&-]{2,}", re.sub(r"['’]s\b", "", title))}


now = datetime.datetime.now(datetime.timezone.utc)
kept = []
kept_keys = []
dropped = {"too old": 0, "blocked source": 0, "stock filler title": 0, "market roundup": 0,
           "not plainly about its category": 0}
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
    category = category_for(article)
    if not category:
        dropped["not plainly about its category"] += 1
        continue
    article["topic"] = category

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

print(f"{total} fetched -> {len(unique)} after URL dedupe -> {len(kept)} after filters and title dedupe")
for reason, count in dropped.items():
    if count:
        print(f"  {count:4} dropped: {reason}")

# Which stories are the day's biggest, for free. Headlines about one story are worded
# differently from outlet to outlet ("Akamai shares jump on $11.6B Anthropic deal",
# "Anthropic strikes $12 billion AI computing deal with Akamai"), but they name the same
# things. So two headlines are taken to be the same story when they share two names that
# are rare in today's news. Names in every other headline ("Fed", "Stock") prove nothing.
name_counts = collections.Counter(w for a in unique.values() for w in story_words(a["title"]))
rare_limit = max(3, len(unique) * 0.02)


def rare_names(article):
    return {w for w in story_words(article["title"]) if name_counts[w] <= rare_limit}


def outlet(source):
    """One name per newsroom: Yahoo Finance UK and Yahoo! Finance Canada are one outlet."""
    words = re.sub(r"^the\s+|[!.]com\b|!", "", source.lower()).split()
    return words[0] if words else source


def pick(pool):
    """The category's biggest stories, one article each, at most MAX_PER_CATEGORY."""
    names = [rare_names(a) for a in pool]
    outlets = []
    for i, article in enumerate(pool):
        carried = {article["source"], *article["also_covered_by"]}
        carried |= {pool[j]["source"] for j in range(len(pool))
                    if j != i and len(names[i] & names[j]) >= 2}
        outlets.append(len({outlet(s) for s in carried}))

    # most outlets first; then GDELT's own measure of how widely it was reported; then newest
    order = sorted(range(len(pool)), key=lambda i: pool[i].get("time_published") or "", reverse=True)
    order.sort(key=lambda i: (-outlets[i], -(pool[i].get("gdelt_weight") or 0)))

    chosen, chosen_names = [], []
    for i in order:
        same = next((c for c, n in zip(chosen, chosen_names) if len(names[i] & n) >= 2), None)
        if same:            # another outlet's take on a story already picked
            same["coverage_count"] += pool[i]["coverage_count"]
            same["also_covered_by"] = sorted({*same["also_covered_by"], pool[i]["source"]})
            continue
        if len(chosen) < MAX_PER_CATEGORY:
            chosen.append(pool[i])
            chosen_names.append(names[i])
    return chosen


picked = []
for category in categories.SOURCE:
    pool = [a for a in kept if a["topic"] == category]
    chosen = pick(pool)
    picked += chosen
    print(f"  {category:17} {len(pool):4} candidates -> {len(chosen)} sent for scoring")
print(f"{len(picked)} articles go to Gemini")

with open(paths.data("filtered.json"), "w") as f:
    json.dump(picked, f, indent=2)
