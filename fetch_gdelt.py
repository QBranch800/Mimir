"""Fetch geopolitics from GDELT's raw event files.

This is the geopolitics source. GDELT's search API refused every request from here, even
the first one of the day ("limit requests to one every 5 seconds"), so this reads the
files GDELT publishes every 15 minutes instead. They are plain downloads with no rate
limit and no key.

Each file lists the events GDELT coded from the news in those 15 minutes: who did what to
whom, in how many articles, and a link to the article it came from. An article is kept
when one of its events is:

- reported by an outlet on the allowlist
- between two different countries, or involving an international body such as the UN,
  which is what makes it geopolitics rather than domestic news
- from the article's opening paragraphs, so it is what the article is about rather than
  something it mentions further down

Articles are ranked by how widely their events were reported. The files carry no
headlines, so only the top few pages are opened, to read their headline, summary and
image.
"""

import csv
import datetime
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
import trafilatura

import paths

INDEX_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
FILE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
LOOKBACK_HOURS = 24
PAGES_TO_READ = 20     # the filter keeps at most ten per category, so this leaves room
                       # for pages that will not open and the same story twice

# Only these outlets. GDELT indexes every site it can find, most of them local papers and
# content farms, and a story that matters is carried by at least one of these.
ALLOWED_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "aljazeera.com",
    "cnbc.com", "bloomberg.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "economist.com", "politico.com", "axios.com", "cnn.com", "npr.org",
    "dw.com", "france24.com", "scmp.com", "thehindu.com", "straitstimes.com",
    "japantimes.co.jp", "channelnewsasia.com", "foreignpolicy.com", "marketwatch.com",
    "barrons.com",
}

# Columns of GDELT 2.0's event export, which has no header row
ACTOR1_CODE, ACTOR1_COUNTRY = 5, 7
ACTOR2_CODE, ACTOR2_COUNTRY = 15, 17
IS_ROOT_EVENT = 25
NUM_ARTICLES = 33
DATE_ADDED = 59
SOURCE_URL = 60

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126 Safari/537.36"}


def allowed_domain(url):
    netloc = urlparse(url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return next((d for d in ALLOWED_DOMAINS if netloc == d or netloc.endswith("." + d)), None)


def download(stamp):
    """One 15 minute file as text, or None if it is missing or unreadable."""
    try:
        response = requests.get(FILE_URL.format(stamp=stamp), timeout=30)
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return archive.read(archive.namelist()[0]).decode("utf-8", "replace")
    except (requests.RequestException, zipfile.BadZipFile, IndexError):
        return None


def is_geopolitical(row):
    countries = {row[ACTOR1_COUNTRY], row[ACTOR2_COUNTRY]} - {""}
    international = len(countries) == 2
    involves_body = row[ACTOR1_CODE].startswith("IGO") or row[ACTOR2_CODE].startswith("IGO")
    return (international or involves_body) and row[IS_ROOT_EVENT] == "1"


def title_from_url(url):
    """A readable headline from the link, for pages that will not open: most of these
    outlets put the headline in the address."""
    slug = max(urlparse(url).path.split("/"), key=len)
    slug = re.sub(r"\.\w+$|[-_]?\d{5,}$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w and not w.isdigit()]
    return " ".join(words).capitalize() if len(words) >= 4 else ""


def read_page(url):
    """Headline, summary, image and outlet name from the page, or None."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        meta = trafilatura.extract_metadata(response.text, default_url=url)
    except Exception:
        meta = None
    title = (meta.title if meta else "") or title_from_url(url)
    if not title:
        return None
    summary = (meta.description if meta else "") or ""
    if meta and not summary:
        summary = trafilatura.extract(response.text) or ""
    return {
        "title": " ".join(title.split()),
        "summary": " ".join(summary.split())[:600],
        "banner_image": (meta.image if meta else "") or "",
        "source": (meta.sitename if meta else "") or allowed_domain(url),
    }


try:
    latest = requests.get(INDEX_URL, timeout=20).text.split()[2]
    newest = datetime.datetime.strptime(latest.rsplit("/", 1)[1][:14], "%Y%m%d%H%M%S")
except (requests.RequestException, IndexError, ValueError) as exc:
    raise SystemExit(f"Could not reach GDELT ({type(exc).__name__}), so "
                     f"gdelt_results.json was left untouched.")

stamps = [(newest - datetime.timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S")
          for i in range(LOOKBACK_HOURS * 4)]
print(f"Downloading {len(stamps)} GDELT files covering the last {LOOKBACK_HOURS} hours...")
with ThreadPoolExecutor(8) as pool:
    files = [text for text in pool.map(download, stamps) if text]
print(f"  got {len(files)} of {len(stamps)}")
if not files:
    raise SystemExit("No GDELT files could be downloaded, so gdelt_results.json was left untouched.")

# each article's weight is how many articles in total reported the events it carries
weight, added = {}, {}
events = 0
for text in files:
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) <= SOURCE_URL:
            continue
        events += 1
        url = row[SOURCE_URL]
        if not is_geopolitical(row) or not allowed_domain(url):
            continue
        weight[url] = weight.get(url, 0) + int(row[NUM_ARTICLES] or 0)
        added[url] = max(added.get(url, ""), row[DATE_ADDED])

ranked = sorted(weight, key=weight.get, reverse=True)
print(f"{events} events -> {len(ranked)} articles from allowlisted outlets about events "
      f"between countries. Reading the top {min(PAGES_TO_READ, len(ranked))}...")

top = ranked[:PAGES_TO_READ]
with ThreadPoolExecutor(6) as pool:
    pages = list(pool.map(read_page, top))

articles, seen_titles = [], set()
for url, page in zip(top, pages):
    if not page or page["title"].lower() in seen_titles:   # bbc.com and bbc.co.uk
        continue
    seen_titles.add(page["title"].lower())
    stamp = added[url]
    articles.append({
        **page,
        "url": url,
        "time_published": f"{stamp[:8]}T{stamp[8:14]}",
        "gdelt_weight": weight[url],
    })
    print(f"  {weight[url]:4}  {page['source'][:18]:18} {page['title'][:80]}")

if not articles:
    raise SystemExit("No GDELT article could be read, so gdelt_results.json was left untouched.")

with open(paths.data("gdelt_results.json"), "w") as f:
    json.dump({"geopolitics": articles}, f, indent=2)
print(f"Saved {len(articles)} articles to gdelt_results.json")
