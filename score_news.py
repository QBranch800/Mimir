import json
import os
import time
import requests
import trafilatura
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

import paths

# override, so the key saved in the data directory always wins over one that
# happens to be in the environment already
load_dotenv(paths.data(".env"), override=True)

# Refuse to call the API without a key rather than sending a request that is bound to
# be rejected. This makes a first run say plainly what is missing, and makes it obvious
# if a key is somehow coming from somewhere other than the file the person edited.
_key = os.getenv("GEMINI_API_KEY")
if not _key:
    raise SystemExit(
        "No Gemini key. Add GEMINI_API_KEY in Settings, or to "
        + paths.data(".env") + " (free key at aistudio.google.com)."
    )
_env_file = paths.data(".env")
_from_file = os.path.exists(_env_file) and any(
    line.strip().startswith("GEMINI_API_KEY=") for line in open(_env_file))
print(f"Using Gemini key from "
      f"{_env_file if _from_file else 'the environment, not from a file'} "
      f"(ends ...{_key[-4:]})")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-3.6-flash"
# Not one big batch. A 134 article request was refused with 503 "high demand" over and
# over while a 5 article one to the same model went through seconds later, so large
# requests get shed when the service is busy, whatever the token limits allow. Batches
# of this size have been served reliably. The cost is that Gemini can only merge
# duplicate stories within a batch, so the same story in two batches stays twice.
BATCH_SIZE = 50
MAX_ATTEMPTS = 3
RETRY_CODES = {429}          # 503 is handled separately: it is not worth retrying
# Every call counts against the free tier's 20 a day, including ones the server fails.
# A clean run costs four: three batches for ~135 articles, plus the second pass.
REQUEST_BUDGET = 8
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

Judge an article by its subject, not by what it mentions in passing. Policy, data or conflict
named as background does not make a company story one of the five categories. Ask what the
article is actually reporting: if the answer is one company's share price, valuation, earnings,
analyst ratings, contracts or prospects, the category is "none" and the score is 1-2, however
weighty the backdrop it cites. For example:
- "These two agribusinesses soar if the US-China summit yields concessions" is a stock call
  using a summit as its premise. It is "none", not geopolitics.
- "Company X could be 26% undervalued after supply deal jitters" is a valuation piece. It is
  "none", not geopolitics, even if the jitters come from a government's trade decision.
- "A new US mine nears startup with EXIM Bank financing" is one project being built. It is
  "none", not US fiscal policy, which means budget, taxation or spending decisions themselves.
The same story told the other way round does belong: "US and China agree agricultural
concessions at summit" is geopolitics, because the agreement is the subject.

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
  "none" if it does not belong to any of the five. Judge this by what the article is reporting,
  not by the publication or section it came from, and not by context it merely mentions.
- The category and the score have to agree. A category other than "none" means the article is
  genuinely about that subject, so it should score at least 3. "none" always scores 1-2.

Give a one-sentence reason for each score. Return one entry per article, using the id given."""


class Score(BaseModel):
    id: int
    score: int
    reason: str
    story_id: int
    category: str


requests_made = 0
out_of_quota = False


def is_daily_quota(error):
    """A daily quota 429 cannot recover during this run, unlike a per-minute one."""
    text = str(error)
    return "429" in text and ("PerDay" in text or "per day" in text)


def score_batch(batch, chars):
    global requests_made, out_of_quota

    lines = []
    for i, article in enumerate(batch):
        lines.append(
            f"id {i} | {article['source']} | {article['coverage_count']} outlet(s) | "
            f"{article['title']} | {article['summary'][:chars]}"
        )

    for attempt in range(MAX_ATTEMPTS):
        if requests_made >= REQUEST_BUDGET:
            print(f"Stopping: this run has already used its budget of {REQUEST_BUDGET} "
                  f"requests, and the free tier only allows 20 a day.")
            return None

        try:
            requests_made += 1
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
            # retrying this one only burns more of today's allowance for nothing
            if is_daily_quota(e):
                out_of_quota = True
                print("Out of Gemini requests for today. The free tier allows 20 a day and "
                      "resets at midnight Pacific.")
                return None
            code = getattr(e, "code", None)
            # A 503 means Gemini is shedding load, which tends to last minutes rather
            # than seconds. Retrying spends the day's allowance on a wall, so give this
            # batch up: its articles stay unscored and the next run will pick them up.
            if code == 503:
                print(f"Gemini is refusing requests right now (503). Leaving these "
                      f"{len(batch)} articles for a later run.")
                return None
            if code not in RETRY_CODES or attempt == MAX_ATTEMPTS - 1:
                print(f"Batch failed: {e}")
                return None
            wait = 10 * 2 ** attempt
            print(f"Error {e.code}, retrying in {wait}s (attempt {attempt + 2} of {MAX_ATTEMPTS}; "
                  f"{requests_made} of {REQUEST_BUDGET} budgeted requests used)...")
            time.sleep(wait)


def fetch_text(url):
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; Mimir/0.1)"})
        response.raise_for_status()
        text = trafilatura.extract(response.text)
    except Exception:
        return ""
    return (text or "")[:TEXT_STAGE_CHARS]


with open(paths.data("filtered.json")) as f:
    articles = json.load(f)

# Scores already earned are kept, so a run that is cut short by a rate limit or an
# outage is not wasted: running again picks up only what is still missing.
previous = {}
if os.path.exists(paths.data("scored.json")):
    try:
        with open(paths.data("scored.json")) as f:
            previous = {a["url"]: a for a in json.load(f) if "significance" in a}
    except (ValueError, KeyError, TypeError):
        print("scored.json could not be read, so everything will be scored afresh.")

current_urls = {a["url"] for a in articles}
scored = [a for url, a in previous.items() if url in current_urls]
todo = [a for a in articles if a["url"] not in previous]

if scored:
    print(f"{len(scored)} articles already have a score and are kept as they are.")
    dropped = len(previous) - len(scored)
    if dropped:
        print(f"{dropped} scored articles are no longer in filtered.json and are discarded.")
if not todo:
    print("Nothing new to score.")

# Stage 1: score from title (and summary where there is one)
for start in range(0, len(todo), BATCH_SIZE):
    batch = todo[start:start + BATCH_SIZE]
    print(f"Scoring articles {start + 1}-{start + len(batch)} of {len(todo)} still to do...")

    scores = score_batch(batch, TITLE_STAGE_CHARS)
    if scores is None:
        if out_of_quota or requests_made >= REQUEST_BUDGET:
            print("Stopping here. Run this again later to score the rest.")
            break
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

    if start + BATCH_SIZE < len(todo):
        time.sleep(13)

if not scored:
    raise SystemExit("Nothing was scored, so scored.json was left untouched.")

# The second pass is an improvement, not a requirement, so skip it rather than spend
# requests we may not have. What was scored above is still saved either way. Only
# articles scored in this run are candidates; earlier ones have already had their turn.
fresh = {a["url"] for a in scored if a["url"] not in previous}
no_summary = [] if (out_of_quota or requests_made >= REQUEST_BUDGET) else \
    [a for a in scored if not a["summary"] and a["url"] in fresh]
if out_of_quota:
    print("Skipping the second scoring pass, since there are no requests left today.")
candidates = sorted(no_summary, key=lambda a: a["significance"], reverse=True)[:TEXT_CANDIDATES]
if candidates:
    print(f"Fetching page text for {len(candidates)} top articles that have no summary...")
for article in candidates:
    text = fetch_text(article["url"])
    if text:
        article["summary"] = text
        article["text_fetched"] = True
    time.sleep(1)

rescore = [a for a in candidates if a.get("text_fetched")]
if candidates:
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

with open(paths.data("scored.json"), "w") as f:
    json.dump(scored, f, indent=2)

# Same data as a script file, so index.html also works when opened directly from the
# file system, where the browser refuses to fetch scored.json.
with open(paths.data("briefing_data.js"), "w") as f:
    f.write("window.MIMIR_DATA = ")
    json.dump(scored, f)
    f.write(";\n")

print(f"Scored {len(scored)} of {len(articles)} articles; "
      f"{len(briefing)} scored {MIN_SCORE} or above. Top 15:")
for article in briefing[:15]:
    print(f"{article['significance']:>2}  x{article['coverage_count']}  [{article['topic']}] {article['title']}")
