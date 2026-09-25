"""Fetch monetary policy headlines from central banks and chosen news desks, over RSS.

This is the monetary policy source. The feeds need no API key, are updated within
minutes, and come from outlets chosen by hand, so none of them is SEO filler. The
central banks publish their own decisions and speeches; the news desks carry what
those mean, which on 09-24 was where the day's best central bank stories were.
"""

import datetime
import email.utils
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

import paths

# (source name, url). Each was checked for how many central bank stories it carries;
# general business and world feeds that carried none were dropped, and so was the Bank
# of Japan's, which is mostly statistics notices. The news desks report its decisions.
FEEDS = [
    # the central banks themselves
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("European Central Bank", "https://www.ecb.europa.eu/rss/press.html"),
    ("Bank of England", "https://www.bankofengland.co.uk/rss/news"),
    # news desks that report on them
    ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),          # finance
    ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),          # economy
    ("The Guardian", "https://www.theguardian.com/business/economics/rss"),
    ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("NPR", "https://feeds.npr.org/1017/rss.xml"),                              # economy
]
TOPIC = "monetary_policy"

# some sites refuse requests that do not look like a browser
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
DC = "{http://purl.org/dc/elements/1.1/}"


def clean(text):
    """Feed text often carries HTML tags and entities; the page wants plain text."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return " ".join(text.split())


def canonical_url(url):
    """Drop tracking parameters, so the same article from two feeds counts once."""
    parts = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if not k.lower().startswith(("utm_", "at_"))]
    return urlunparse(parts._replace(query=urlencode(query), fragment=""))


def published(item):
    """The item's publication time as the pipeline's YYYYMMDDTHHMMSS, in UTC."""
    for tag in ("pubDate", DC + "date", ATOM + "published", ATOM + "updated"):
        raw = (item.findtext(tag) or "").strip()
        if not raw:
            continue
        try:
            when = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            try:
                when = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        return when.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return ""


def image(item):
    for tag in (MEDIA + "content", MEDIA + "thumbnail"):
        for node in item.findall(tag):
            if node.get("url") and node.get("medium", "image") == "image":
                return node.get("url")
    enclosure = item.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image"):
        return enclosure.get("url") or ""
    return ""


def link(item):
    href = (item.findtext("link") or "").strip()
    if href:
        return href
    node = item.find(ATOM + "link")
    return node.get("href", "") if node is not None else ""


def parse(source, content):
    root = ET.fromstring(content)
    items = root.findall(".//item") or root.findall(".//" + ATOM + "entry")
    articles = []
    for item in items:
        title = clean(item.findtext("title") or item.findtext(ATOM + "title"))
        url = link(item)
        if not title or not url:
            continue
        articles.append({
            "title": title,
            "url": canonical_url(url),
            "source": source,
            "time_published": published(item),
            "summary": clean(item.findtext("description") or item.findtext(ATOM + "summary"))[:600],
            "banner_image": image(item),
        })
    return articles


results = {}
worked = 0
for source, url in FEEDS:
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        articles = parse(source, response.content)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"Skipping {source} ({urlparse(url).netloc}): {type(exc).__name__}")
        continue
    worked += 1
    results.setdefault(TOPIC, []).extend(articles)
    print(f"{source:28} {len(articles):3} items")
    time.sleep(0.5)

if not worked:
    raise SystemExit("No RSS feed could be read, so rss_results.json was left untouched.")

total = sum(len(v) for v in results.values())
with open(paths.data("rss_results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"Saved {total} articles from {worked} of {len(FEEDS)} feeds to rss_results.json")
