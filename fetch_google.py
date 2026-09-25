"""Fetch US fiscal policy, US macro data and tech and AI headlines from Google News.

This is the source for those three categories. Each is fetched by searching for the
words that define it, rather than by a provider's own topic labels: Alpha Vantage's
labels filed hundreds of stock-filler pieces a day under "fiscal" and "macro", and not
one real fiscal or macro story. Searching returns the outlets that actually cover the
subject, within minutes, and needs no key.

Google gives a headline and outlet for each result, but no summary, and links that go
through a Google redirect, so the scorer judges these from their headlines.

Each category runs several short searches rather than one long one: Google ignored the
"last day" limit on a search with a dozen alternatives in it, and returned stories
from months ago.
"""

import datetime
import email.utils
import html
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

import paths

SEARCH_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
QUERIES = {
    "us_fiscal_policy": [
        '"government shutdown" OR "funding bill" OR "continuing resolution" OR "stopgap"',
        '"debt ceiling" OR "federal deficit" OR "national debt" OR "Congressional Budget Office"',
        '"appropriations" OR "spending bill" OR "federal budget" OR "budget reconciliation"',
        '"tax bill" OR "tax cuts" OR "tax credit" Congress',
    ],
    "us_macro_data": [
        '"jobless claims" OR "jobs report" OR "nonfarm payrolls" OR "unemployment rate"',
        '"consumer price index" OR "CPI" OR "PCE" inflation US',
        '"GDP" US economy',
        '"retail sales" OR "consumer sentiment" OR "consumer confidence" US',
        '"PMI" OR "ISM" OR "durable goods" OR "housing starts" OR "home sales" US',
    ],
    "tech_and_ai": [
        '"OpenAI" OR "Anthropic" OR "xAI" OR "DeepMind" OR "Meta AI"',                  # AI labs
        '"Nvidia" OR "TSMC" OR "AMD" OR "Broadcom" OR "ASML" OR "AI chips"',              # chipmakers
        '"Microsoft" OR "Amazon Web Services" OR "Google Cloud" OR "Oracle" AI',          # cloud giants
        '"data center" OR "export controls" OR "AI regulation" OR "antitrust" tech',
    ],
}
LOOKBACK = "1d"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126 Safari/537.36"}


def search(query):
    url = SEARCH_URL.format(query=quote(f"{query} when:{LOOKBACK}"))
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return ET.fromstring(response.content).findall(".//item")


def article(item):
    source = (item.findtext("source") or "").strip()
    title = html.unescape(item.findtext("title") or "").strip()
    # Google appends the outlet to every headline: "Jobless claims fall - Reuters"
    if source and title.endswith(" - " + source):
        title = title[: -len(" - " + source)]
    try:
        when = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
        published = when.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    except (TypeError, ValueError):
        published = ""
    return {
        "title": title,
        "url": (item.findtext("link") or "").strip(),
        "source": source,
        "time_published": published,
        "summary": "",
        "banner_image": "",
    }


results = {}
worked = 0
for category, queries in QUERIES.items():
    seen = set()
    for query in queries:
        try:
            items = search(query)
        except (requests.RequestException, ET.ParseError) as exc:
            print(f"Skipping a {category} search: {type(exc).__name__}")
            continue
        worked += 1
        for item in items:
            found = article(item)
            if found["title"] and found["url"] and found["url"] not in seen:
                seen.add(found["url"])
                results.setdefault(category, []).append(found)
        time.sleep(1)
    print(f"{category:17} {len(results.get(category, [])):4} articles")

if not worked:
    raise SystemExit("Google News could not be reached, so google_results.json was left untouched.")

with open(paths.data("google_results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved {sum(len(v) for v in results.values())} articles to google_results.json")
