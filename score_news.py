import json
import os
import time
import requests
import trafilatura
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-3.6-flash"
BATCH_SIZE = 150
MAX_ATTEMPTS = 4
RETRY_CODES = {429, 503}
MIN_SCORE = 4
TEXT_CANDIDATES = 20
TITLE_STAGE_CHARS = 300
TEXT_STAGE_CHARS = 1500

SYSTEM_PROMPT = """You rate news articles for a daily briefing that covers exactly five categories.
Score an article's significance only in relation to these:

1. Monetary policy: central bank actions, statements, rate decisions, speeches, or meeting
   minutes from the Fed, ECB, BoE, BoJ, or other major central banks.
2. US fiscal policy: US government budget, taxation, spending, or debt/deficit policy actions.
3. US macroeconomic data: CPI, jobs reports, GDP, PMI, retail sales, and other major US
   economic releases.
4. Geopolitics: events with material economic or market relevance, such as conflicts,
   sanctions, elections, trade policy, or major diplomatic developments.
5. Tech and AI: technology developments with material economic or market relevance, such as
   major AI capability or infrastructure announcements, semiconductor capacity and supply,
   large capital investment in data centres or fabrication, and technology regulation or
   antitrust. Product launches, app updates, gadget reviews, and routine single-company
   earnings or share price moves do not belong here.

An article that does not fall into any of these five categories is noise for this briefing,
whatever else it is about, and should score 1-2 even if it involves a well-known company or a
large dollar figure.

Score each article's significance from 1 to 10:
- 9-10: a major event in one of the five categories that could move whole markets or the
  economy (a rate decision, a surprise CPI print, a war or major sanctions package, a
  government shutdown or debt-ceiling resolution)
- 6-8: a real development in one of the five categories, but narrower or incremental (a
  central bank official's speech, a single data revision, a regional escalation, a trade
  policy proposal)
- 3-5: only loosely touches one of the five categories, or is a minor and expected data point
- 1-2: does not meaningfully relate to any of the five categories (single-company news,
  analyst commentary, product launches, routine corporate filings, industry press releases)

Each article line shows: id | source | how many outlets covered the story | title | summary.
- Some articles have no summary, only a title. Score those conservatively and do not assume
  details the title does not state.
- Wider coverage (more outlets) is a mild signal that a story matters, but never a reason on
  its own to score high.
- Give each article a story_id. Articles about the same underlying event or story must share
  the same story_id, and unrelated articles must have different story_ids.
- Give each article the category it belongs to, as one of exactly these strings:
  "monetary_policy", "us_fiscal_policy", "us_macro_data", "geopolitics", "tech_and_ai", or
  "none" if it does not belong to any of the five. Judge this by what the article is actually about, not by the
  publication or section it came from.

Give a one-sentence reason for each score. Return one entry per article, using the id given."""


class Score(BaseModel):
    id: int
    score: int
    reason: str
    story_id: int
    category: str


def score_batch(batch, chars):
    lines = []
    for i, article in enumerate(batch):
        lines.append(
            f"id {i} | {article['source']} | {article['coverage_count']} outlet(s) | "
            f"{article['title']} | {article['summary'][:chars]}"
        )

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents="\n".join(lines),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=list[Score],
                    temperature=0,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            retryable = getattr(e, "code", None) in RETRY_CODES
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                print(f"Batch failed: {e}")
                return None
            wait = 10 * 2 ** attempt
            print(f"Error {e.code}, retrying in {wait}s (attempt {attempt + 2} of {MAX_ATTEMPTS})...")
            time.sleep(wait)


def fetch_text(url):
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; Mimir/0.1)"})
        response.raise_for_status()
        text = trafilatura.extract(response.text)
    except Exception:
        return ""
    return (text or "")[:TEXT_STAGE_CHARS]


with open("filtered.json") as f:
    articles = json.load(f)

# Stage 1: score everything from title (and summary where there is one)
scored = []
for start in range(0, len(articles), BATCH_SIZE):
    batch = articles[start:start + BATCH_SIZE]
    print(f"Scoring articles {start + 1}-{start + len(batch)} of {len(articles)}...")

    scores = score_batch(batch, TITLE_STAGE_CHARS)
    if scores is None:
        continue

    # articles about the same story share a story_id: keep only the best-scoring one
    stories = {}
    for item in scores:
        if 0 <= item["id"] < len(batch):
            stories.setdefault(item["story_id"], []).append((item, batch[item["id"]]))

    for members in stories.values():
        best_item, best = max(members, key=lambda m: m[0]["score"])
        best["significance"] = best_item["score"]
        best["significance_reason"] = best_item["reason"]
        best["category"] = best_item["category"]
        for _, other in members:
            if other is not best:
                best["coverage_count"] += other["coverage_count"]
                best["also_covered_by"] += [other["source"]] + other["also_covered_by"]
        best["also_covered_by"] = sorted(set(best["also_covered_by"]))
        scored.append(best)

    if start + BATCH_SIZE < len(articles):
        time.sleep(13)

if not scored:
    raise SystemExit("Nothing was scored, so scored.json was left untouched.")

no_summary = [a for a in scored if not a["summary"]]
candidates = sorted(no_summary, key=lambda a: a["significance"], reverse=True)[:TEXT_CANDIDATES]
print(f"Fetching page text for {len(candidates)} top articles that have no summary...")
for article in candidates:
    text = fetch_text(article["url"])
    if text:
        article["summary"] = text
        article["text_fetched"] = True
    time.sleep(1)

rescore = [a for a in candidates if a.get("text_fetched")]
print(f"Got text for {len(rescore)} of {len(candidates)}. Scoring those again...")
if rescore:
    scores = score_batch(rescore, TEXT_STAGE_CHARS)
    if scores:
        for item in scores:
            if 0 <= item["id"] < len(rescore):
                article = rescore[item["id"]]
                article["first_pass_significance"] = article["significance"]
                article["significance"] = item["score"]
                article["significance_reason"] = item["reason"]
                article["category"] = item["category"]


scored.sort(key=lambda a: (a["significance"], a["coverage_count"]), reverse=True)
briefing = [a for a in scored if a["significance"] >= MIN_SCORE]

with open("scored.json", "w") as f:
    json.dump(scored, f, indent=2)

# Same data as a script file, so index.html also works when opened directly from the
# file system, where the browser refuses to fetch scored.json.
with open("briefing_data.js", "w") as f:
    f.write("window.MIMIR_DATA = ")
    json.dump(scored, f)
    f.write(";\n")

print(f"Scored {len(scored)} of {len(articles)} articles; "
      f"{len(briefing)} scored {MIN_SCORE} or above. Top 15:")
for article in briefing[:15]:
    print(f"{article['significance']:>2}  x{article['coverage_count']}  [{article['topic']}] {article['title']}")
