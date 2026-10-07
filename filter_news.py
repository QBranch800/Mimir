import collections
import datetime
import difflib
import json
import os
import re

import categories
import paths

BLOCKED_SOURCES = {
    "MarketBeat", "CBIZ", "AD HOC NEWS", "Kalkine Media",
    "Stock Titan", "Insider Monkey", "Pluang", "scanx.trade",
    "Simply Wall St", "Simply Wall Street",
    "富途牛牛", "Futubull", "Moomoo",
}
BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\b[\d,]+ shares\b", re.I),
    re.compile(r"\b(takes?|buys?|acquires?|sells?)\b.*\b(position|stake|shares)\b", re.I),
    re.compile(r"\bstock holdings\b", re.I),
    re.compile(r"\b(average|consensus) (rating|recommendation)\b", re.I),
    re.compile(r"^(what|why|could|is|are|has|does|do)\b.{0,80}\([A-Z]{2,6}:[A-Z.]+\)", re.I),
    re.compile(r"\bstock (edges|gains?|holds?|slips?|trades?|heads?|dips?|climbs?)\b", re.I),
    re.compile(r"\bstocks? (is |are )?(surg|soar|jump|plung|tumbl|ralli|rall|sink|spik|"
               r"crater|slump|skyrocket)\w*", re.I),
    re.compile(r"\b(pre-?market|after-?hours) (trading|move|gains?|losses?|today)\b", re.I),
    re.compile(r"\bwhich .{0,40}\bis (a|the) better buy\b", re.I),
    re.compile(r"\b(stock|shares) an? (buy|sell)\b|\bshould you buy\b|\bstocks? to buy\b", re.I),
    re.compile(r"\bshares are (falling|rising|soaring|plunging|trading)\b", re.I),
    re.compile(r"\b(opened|moved|closed) (up|down) by [\d.]+%", re.I),
    re.compile(r"\bstock price, news, quote\b", re.I),
    re.compile(r"\bzacks\b", re.I),
    re.compile(r"\bmarket chatter\b", re.I),
    re.compile(r"\binvestigating (allegations|claims)\b|\bclass action\b|\bshareholder (alert|rights)\b", re.I),
    re.compile(r"^(file )?photos?\b|\bfile photo\b", re.I),
]

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

MAX_AGE_HOURS = 24

MAX_PER_CATEGORY = 10

SOURCE_FILES = {
    "rss_results.json": "rss",
    "google_results.json": "google",
    "gdelt_results.json": "gdelt",
}

MACRO_RELEASES = [re.compile(p, re.I) for p in (
    r"jobless claims", r"payrolls|jobs report|unemployment rate", r"job openings|\bjolts\b",
    r"\bcpi\b|consumer price", r"\bpce\b", r"\bgdp\b|gross domestic product",
    r"\bism\b", r"\bpmi\b|purchasing managers", r"retail sales", r"new[- ]home sales",
    r"existing[- ]home sales|pending[- ]home sales", r"housing starts|building permits",
    r"durable goods", r"consumer (?:confidence|sentiment)", r"industrial production",
    r"trade deficit",
)]

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
                    article["topic"] = hint
                    unique[article["url"]] = article

if not unique:
    raise SystemExit("No fetched news to filter. Run the fetch steps first.")


def normalize_title(title):
    title = title.lower()
    title = re.sub(r"\s+by (reuters|investing\.com|bloomberg)$", "", title)
    title = re.sub(r"[^a-z0-9 ]", "", title)
    return " ".join(title.split())


def age_hours(article, now):
    stamp = (article.get("time_published") or "").rstrip("Z")
    try:
        when = datetime.datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return (now - when.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 3600


def category_for(article):
    options = categories.categories_of(article["feed"])
    options.sort(key=lambda c: c != article["topic"])
    return next((c for c in options if categories.on_topic(article, c)), None)


def story_words(title):
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

name_counts = collections.Counter(w for a in unique.values() for w in story_words(a["title"]))
rare_limit = max(3, len(unique) * 0.02)


def rare_names(article):
    return {w for w in story_words(article["title"]) if name_counts[w] <= rare_limit}


def outlet(source):
    words = re.sub(r"^the\s+|[!.]com\b|!", "", source.lower()).split()
    return words[0] if words else source


def release(article):
    return next((i for i, p in enumerate(MACRO_RELEASES) if p.search(article["title"])), None)


def pick(pool):
    names = [rare_names(a) for a in pool]
    releases = [release(a) if a["topic"] == "us_macro_data" else None for a in pool]

    def same_story(i, j):
        return len(names[i] & names[j]) >= 2 or (releases[i] is not None and releases[i] == releases[j])

    outlets = []
    for i, article in enumerate(pool):
        carried = {article["source"], *article["also_covered_by"]}
        carried |= {pool[j]["source"] for j in range(len(pool)) if j != i and same_story(i, j)}
        outlets.append(len({outlet(s) for s in carried}))

    order = sorted(range(len(pool)), key=lambda i: pool[i].get("time_published") or "", reverse=True)
    order.sort(key=lambda i: (-outlets[i], -(pool[i].get("gdelt_weight") or 0)))

    chosen = []
    for i in order:
        same = next((c for c in chosen if same_story(i, c)), None)
        if same is not None:
            kept_one = pool[same]
            kept_one["coverage_count"] += pool[i]["coverage_count"]
            kept_one["also_covered_by"] = sorted({*kept_one["also_covered_by"], pool[i]["source"]})
            continue
        if len(chosen) < MAX_PER_CATEGORY:
            chosen.append(i)
    return [pool[i] for i in chosen]


picked = []
for category in categories.SOURCE:
    pool = [a for a in kept if a["topic"] == category]
    chosen = pick(pool)
    picked += chosen
    print(f"  {category:17} {len(pool):4} candidates -> {len(chosen)} sent for scoring")
print(f"{len(picked)} articles go to Gemini")

with open(paths.data("filtered.json"), "w") as f:
    json.dump(picked, f, indent=2)
