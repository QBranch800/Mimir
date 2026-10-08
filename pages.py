import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
GOOGLE_NEWS = "https://news.google.com/"


def canonical_url(url):
    parts = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if not k.lower().startswith(("utm_", "at_"))]
    return urlunparse(parts._replace(query=urlencode(query), fragment=""))


def read_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        meta = trafilatura.extract_metadata(response.text, default_url=url)
        if meta is None:
            return None
        summary = meta.description or trafilatura.extract(response.text) or ""
    except Exception:
        return None
    return {
        "title": " ".join((meta.title or "").split()),
        "summary": " ".join(summary.split())[:600],
        "banner_image": meta.image or "",
        "source": meta.sitename or "",
    }


def read_text(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return " ".join((trafilatura.extract(response.text) or "").split())
    except Exception:
        return ""


def is_google_news(url):
    return url.startswith(GOOGLE_NEWS)


def resolve_google_news(url):
    try:
        article_id = urlparse(url).path.rsplit("/", 1)[-1]
        page = requests.get(GOOGLE_NEWS + "rss/articles/" + article_id,
                            headers=HEADERS, timeout=15).text
        signature = re.search(r'data-n-a-sg="([^"]+)"', page)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (signature and timestamp):
            return None
        request = ["garturlreq",
                   [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                     None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                   article_id, int(timestamp.group(1)), signature.group(1)]
        response = requests.post(
            GOOGLE_NEWS + "_/DotsSplashUi/data/batchexecute",
            data={"f.req": json.dumps([[["Fbv4je", json.dumps(request), None, "generic"]]])},
            headers=HEADERS, timeout=15)
        for line in response.text.splitlines():
            if line.startswith('[["wrb.fr"'):
                reply = json.loads(json.loads(line)[0][2])
                return canonical_url(reply[1])
    except Exception:
        return None
    return None
