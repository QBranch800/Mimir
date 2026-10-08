import csv
import datetime
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

import pages
import paths

INDEX_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
FILE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
LOOKBACK_HOURS = 24
PAGES_TO_READ = 20

ALLOWED_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "aljazeera.com",
    "cnbc.com", "bloomberg.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "economist.com", "politico.com", "axios.com", "cnn.com", "npr.org",
    "dw.com", "france24.com", "scmp.com", "thehindu.com", "straitstimes.com",
    "japantimes.co.jp", "channelnewsasia.com", "foreignpolicy.com", "marketwatch.com",
    "barrons.com",
}

ACTOR1_CODE, ACTOR1_COUNTRY = 5, 7
ACTOR2_CODE, ACTOR2_COUNTRY = 15, 17
IS_ROOT_EVENT = 25
NUM_ARTICLES = 33
DATE_ADDED = 59
SOURCE_URL = 60


def allowed_domain(url):
    netloc = urlparse(url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return next((d for d in ALLOWED_DOMAINS if netloc == d or netloc.endswith("." + d)), None)


def download(stamp):
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
    slug = max(urlparse(url).path.split("/"), key=len)
    slug = re.sub(r"\.\w+$|[-_]?\d{5,}$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w and not w.isdigit()]
    return " ".join(words).capitalize() if len(words) >= 4 else ""


def describe(url):
    page = pages.read_page(url) or {}
    title = page.get("title") or title_from_url(url)
    if not title:
        return None
    return {
        "title": title,
        "summary": page.get("summary", ""),
        "banner_image": page.get("banner_image", ""),
        "source": page.get("source") or allowed_domain(url),
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

weight, added = {}, {}
events = 0
for text in files:
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    except csv.Error:
        continue
    for row in rows:
        if len(row) <= SOURCE_URL:
            continue
        events += 1
        url = row[SOURCE_URL]
        if not is_geopolitical(row) or not allowed_domain(url):
            continue
        count = row[NUM_ARTICLES]
        weight[url] = weight.get(url, 0) + (int(count) if count.isdigit() else 0)
        added[url] = max(added.get(url, ""), row[DATE_ADDED])

ranked = sorted(weight, key=weight.get, reverse=True)
print(f"{events} events -> {len(ranked)} articles from allowlisted outlets about events "
      f"between countries. Reading the top {min(PAGES_TO_READ, len(ranked))}...")

top = ranked[:PAGES_TO_READ]
with ThreadPoolExecutor(6) as pool:
    described = list(pool.map(describe, top))

articles, seen_titles = [], set()
for url, page in zip(top, described):
    if not page or page["title"].lower() in seen_titles:
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
