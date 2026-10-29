import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
GOOGLE_NEWS = "https://news.google.com/"
SUMMARY_LIMIT = 600
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "corp", "inc", "ltd", "co", "gov",
                 "sen", "rep", "gen", "lt", "no", "vs", "jan", "feb", "mar", "apr", "jun", "jul",
                 "aug", "sep", "sept", "oct", "nov", "dec", "est", "approx", "dept", "univ"}
SENTENCE_END = re.compile(r"[.!?][\"'’”)\]]*(?=\s+[^a-z\s]|\s*$)")


def sentence_ends(text):
    for match in SENTENCE_END.finditer(text):
        end = match.end()
        if match.group()[0] == "." and text[match.start() - 1:match.start()] == ".":
            continue
        word = (text[:match.start()].split() or [""])[-1].lstrip("\"'‘“(")
        if (match.group()[0] == "." and end < len(text)
                and (len(word) == 1 or re.fullmatch(r"[A-Za-z](\.[A-Za-z])+", word)
                     or word.lower() in ABBREVIATIONS)):
            continue
        yield end


def whole_sentences(text, limit=SUMMARY_LIMIT):
    text = " ".join((text or "").split())
    cut = 0
    for end in sentence_ends(text):
        if end > limit and cut:
            break
        cut = end
    return text[:cut]


def is_whole(text):
    return bool(text) and whole_sentences(text, len(text)) == text


def summary_from(description, body):
    description = " ".join((description or "").split())
    if is_whole(description):
        return whole_sentences(description)
    paragraphs = [" ".join(p.split()) for p in (body or "").split("\n")]
    stem = re.sub(r"\s*(\.\.\.|…)$", "", description).rsplit(" ", 1)[0][:80]
    if len(stem) >= 30:
        for paragraph in paragraphs:
            start = paragraph.find(stem)
            if start >= 0 and whole_sentences(paragraph[start:]):
                return whole_sentences(paragraph[start:])
    if whole_sentences(description):
        return whole_sentences(description)
    for paragraph in paragraphs:
        if len(paragraph.split()) >= 12 and whole_sentences(paragraph):
            return whole_sentences(paragraph)
    return ""


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
        description = " ".join((meta.description or "").split())
        body = "" if is_whole(description) else trafilatura.extract(response.text) or ""
        summary = summary_from(description, body)
    except Exception:
        return None
    return {
        "title": " ".join((meta.title or "").split()),
        "summary": summary,
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
