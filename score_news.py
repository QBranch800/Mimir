import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

import categories
import pages
import paths

load_dotenv(paths.data(".env"), override=True)

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

MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
BATCH_SIZE = 50
MAX_ATTEMPTS = 3
RETRY_CODES = {429}
REQUEST_BUDGET = 8
SECOND_CHANCE_WAIT = 30
VERIFY_WAIT = 20
MIN_SCORE = 4
SUMMARY_CHARS = 300

SYSTEM_PROMPT = """You rate news articles for a daily briefing that covers exactly five categories.
Score an article's significance only in relation to these:

1. Monetary policy: central bank actions, statements, rate decisions, speeches, or meeting
   minutes from the Fed, ECB, BoE, BoJ, or other major central banks.
2. US fiscal policy: US government budget, taxation, spending, or debt/deficit policy actions.
3. US macroeconomic data: CPI, jobs reports, GDP, PMI, retail sales, and other major US
   economic releases.
4. Geopolitics: events with material economic or market relevance, such as conflicts,
   sanctions, elections, trade policy, or major diplomatic developments.
5. Tech and AI: major moves by the companies that shape AI and computing: the big AI labs
   (OpenAI, Anthropic, Google DeepMind, Meta, xAI and their peers), the hyperscalers and
   cloud giants (Microsoft, Amazon, Google, Oracle), and the chipmakers (Nvidia, TSMC, AMD,
   Intel, Broadcom, ASML). That means new frontier models, very large compute, chip or data
   centre deals, chip capacity and supply, and serious AI safety or security incidents; plus
   technology regulation, export controls and antitrust. Stock picks, dividends, share price
   moves, analyst ratings, routine earnings, and minor product or app updates do not belong
   here.

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
- "L3Harris awarded $876 million Navy contract" is one company winning a contract. It is
  "none", not US fiscal policy, however large the sum.
- "Medicare lab fee changes hit BillionToOne and CareDx" is about two companies' revenue. It is
  "none". A rule change reported as its effect on named companies is a company story.
- "Why is X stock surging premarket?" is a share price move. It is always "none".
The same story told the other way round does belong: "US and China agree agricultural
concessions at summit" is geopolitics, because the agreement is the subject.

Tech and AI is the exception to the one-company rule, because there a single company's move
is often the news itself. A major move by one of the AI labs, hyperscalers, cloud giants or
chipmakers named above belongs in tech_and_ai: "Anthropic signs $11.6 billion computing deal
with Akamai", "OpenAI releases a new frontier model", "Rogue AI model breaks into a government
website". If a headline leads with the share price but the cause is such a move, as in
"Akamai shares jump 26% after $11.6 billion Anthropic deal", judge the move. Their share
prices, valuations, dividends, analyst ratings and stock picks are still "none", as are
smaller companies' products and contracts.

Keep to the level each category names:
- US fiscal policy means the US federal government: Congress, the Treasury, the White House
  budget, federal taxes and federal spending decisions. A state legislature, a city council, a
  utility's rates or a regulator's fee schedule is not it, even when money is involved.
- Monetary policy means central banks: the Fed, ECB, BoE, BoJ and their peers setting rates,
  guidance, balance sheets or the money itself. Commercial banks building products, even
  digital money products, are not monetary policy.
- If an article sits on the edge of a category, it does not belong there. It is better for a
  category to have nothing today than to fill it with something that only nearly fits.

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


PROMPT_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]


CATEGORY_KEYS = ["monetary_policy", "us_fiscal_policy", "us_macro_data", "geopolitics",
                 "tech_and_ai"]

VERIFY_PROMPT = """You check the finalists of a daily market briefing before anyone reads
them. Each line gives an article and the category it was filed under. Say which category
the article genuinely belongs to: usually the one it was filed under, sometimes another,
often none.

- monetary_policy: central banks setting interest rates, guidance, balance sheets or money
  itself (the Fed, ECB, Bank of England, Bank of Japan and their peers), including what their
  leaders say about policy in speeches, testimony and minutes. Commercial banks, even
  building money-like products, are not monetary policy.
- us_fiscal_policy: the US federal government's budget, taxes, spending and debt (Congress,
  the Treasury, the White House budget). Not states, cities, utilities or fee schedules.
- us_macro_data: US economic releases and what they show: CPI, jobs, GDP, PMI, retail sales.
- geopolitics: conflicts, sanctions, elections, trade policy and diplomacy with economic or
  market weight.
- tech_and_ai: major moves by the big AI labs (OpenAI, Anthropic, Google DeepMind, Meta, xAI),
  the hyperscalers and cloud giants (Microsoft, Amazon, Google, Oracle) and the chipmakers
  (Nvidia, TSMC, AMD, Intel, Broadcom, ASML): new frontier models, very large compute, chip
  or data centre deals, chip supply, serious AI safety or security incidents; plus tech
  regulation, export controls and antitrust.

The answer is "none" when the article is really about one company (its shares, valuation,
earnings, analyst ratings, contracts, products or prospects), even if it names a policy, a
war or a data release as background. The exception is tech_and_ai: a major move by one of
the companies named there is the news itself, even when the headline leads with a share
price. Their share prices, dividends and stock picks are still none. It is also "none" when
the article only nearly fits.
When unsure, say none: the briefing would rather show nothing in a category than something
wrong.

If two articles report the same event, set same_event_as on the later one to the id of the
earlier one. Otherwise set it to -1.

Give a one-sentence reason. Return one entry per article, using the id given."""

VERIFY_VERSION = hashlib.sha256(VERIFY_PROMPT.encode()).hexdigest()[:12]
FINALISTS_PER_CATEGORY = 3

EXPLAIN_PROMPT = """You write the short explanation shown under each story in a daily market
briefing. Each article comes with its category, outlet and headline, a short summary, and,
when the outlet allows it, part of the article's own text.

For each one, write three to five plain sentences, about 60 to 100 words, saying what
happened and why it matters for markets or the economy. Use only facts stated in what you
are given: never add numbers, names, dates or causes it does not contain. If you are given
little more than a headline, write one or two sentences that explain it without adding
anything. Do not open by repeating the headline.

Return one entry per article, using the id given."""

EXPLAIN_VERSION = hashlib.sha256(EXPLAIN_PROMPT.encode()).hexdigest()[:12]
ARTICLE_CHARS = 1500


class Verdict(BaseModel):
    id: int
    category: str
    same_event_as: int
    reason: str


class Explanation(BaseModel):
    id: int
    explainer: str


class Score(BaseModel):
    id: int
    score: int
    reason: str
    story_id: int
    category: str


requests_made = 0
out_of_quota = False
exhausted = set()
overloaded = set()
last_model = None


def is_daily_quota(error):
    text = str(error)
    return "429" in text and ("PerDay" in text or "per day" in text)


def score_batch(batch, chars, models=None):
    lines = []
    for i, article in enumerate(batch):
        lines.append(
            f"id {i} | {article['source']} | {article['coverage_count']} outlet(s) | "
            f"{article['title']} | {article['summary'][:chars]}"
        )
    return ask("\n".join(lines), len(batch), SYSTEM_PROMPT, list[Score], models)


def ask(contents, size, system, schema, models=None):
    global out_of_quota, last_model

    for model in (models or MODELS):
        if model in exhausted or model in overloaded:
            continue
        result = _try_model(model, contents, system, schema)
        if result == "next":
            continue
        if result is not None:
            last_model = model
        return result

    if len(exhausted) == len(MODELS):
        out_of_quota = True
        print("Every model is out of requests for today. The free tier resets at "
              "midnight US Pacific.")
    else:
        print(f"Every model refused this request. Leaving these {size} articles "
              f"for a later run.")
    return None


def _try_model(model, contents, system, schema):
    global requests_made

    for attempt in range(MAX_ATTEMPTS):
        if requests_made >= REQUEST_BUDGET:
            print(f"Stopping: this run has already used its budget of {REQUEST_BUDGET} "
                  f"requests.")
            return None

        try:
            requests_made += 1
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            if is_daily_quota(e):
                exhausted.add(model)
                print(f"{model} is out of requests for today, trying the next model.")
                return "next"
            code = getattr(e, "code", None)
            if code in (503, 404):
                overloaded.add(model)
                reason = "is overloaded (503)" if code == 503 else "is not available (404)"
                print(f"{model} {reason}, using the next model for the rest of this run.")
                return "next"
            if code not in RETRY_CODES or attempt == MAX_ATTEMPTS - 1:
                print(f"Batch failed on {model}: {e}")
                return None
            wait = 10 * 2 ** attempt
            print(f"Error {e.code}, retrying in {wait}s (attempt {attempt + 2} of {MAX_ATTEMPTS}; "
                  f"{requests_made} of {REQUEST_BUDGET} budgeted requests used)...")
            time.sleep(wait)


with open(paths.data("filtered.json")) as f:
    articles = json.load(f)

previous = {}
if os.path.exists(paths.data("scored.json")):
    try:
        with open(paths.data("scored.json")) as f:
            loaded = [a for a in json.load(f) if "significance" in a]
        previous = {a["url"]: a for a in loaded if a.get("prompt_version") == PROMPT_VERSION}
        stale = len(loaded) - len(previous)
        if stale:
            print(f"{stale} articles were scored under an earlier version of the prompt, "
                  f"so they will be scored again.")
    except (ValueError, KeyError, TypeError):
        print("scored.json could not be read, so everything will be scored afresh.")

current = {a["url"]: a for a in articles}
scored = [a for url, a in previous.items() if url in current]
for article in scored:
    article["feed"] = current[article["url"]]["feed"]
    article["topic"] = current[article["url"]]["topic"]
    if current[article["url"]]["summary"]:
        article["summary"] = current[article["url"]]["summary"]
todo = [a for a in articles if a["url"] not in previous]

if scored:
    print(f"{len(scored)} articles already have a score and are kept as they are.")
    dropped = len(previous) - len(scored)
    if dropped:
        print(f"{dropped} scored articles are no longer in filtered.json and are discarded.")
if not todo:
    print("Nothing new to score.")

todo.sort(key=lambda a: a.get("topic") or "")


def read_google_story(article):
    real = pages.resolve_google_news(article["url"])
    if not real:
        return
    article["article_url"] = real
    page = pages.read_page(real)
    if page:
        article["summary"] = page["summary"]
        article["banner_image"] = page["banner_image"]


google = [a for a in todo if pages.is_google_news(a["url"])]
if google:
    print(f"Reading the pages behind {len(google)} Google News stories...")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(read_google_story, google))
    print(f"  found {sum(1 for a in google if a.get('article_url'))} of them; "
          f"{sum(1 for a in google if a['summary'])} had a summary and "
          f"{sum(1 for a in google if a['banner_image'])} an image")


def score_and_record(batch):
    scores = score_batch(batch, SUMMARY_CHARS)
    if scores is None:
        return False

    stories = {}
    for item in scores:
        if 0 <= item["id"] < len(batch):
            stories.setdefault(item["story_id"], []).append((item, batch[item["id"]]))

    for members in stories.values():
        best_item, best = max(members, key=lambda m: m[0]["score"])
        best["significance"] = best_item["score"]
        best["significance_reason"] = best_item["reason"]
        best["category"] = best_item["category"]
        best["scored_by"] = last_model
        best["prompt_version"] = PROMPT_VERSION
        for _, other in members:
            if other is not best:
                best["coverage_count"] += other["coverage_count"]
                best["also_covered_by"] += [other["source"]] + other["also_covered_by"]
        best["also_covered_by"] = sorted(set(best["also_covered_by"]))
        scored.append(best)
        for _, other in members:
            if other is not best:
                other.update({"significance": 0, "category": "none", "merged_into": best["url"],
                              "significance_reason": "Same story as another article.",
                              "scored_by": last_model, "prompt_version": PROMPT_VERSION})
                scored.append(other)

    return True


for start in range(0, len(todo), BATCH_SIZE):
    batch = todo[start:start + BATCH_SIZE]
    print(f"Scoring articles {start + 1}-{start + len(batch)} of {len(todo)} still to do...")
    if not score_and_record(batch):
        if out_of_quota or requests_made >= REQUEST_BUDGET:
            print("Stopping here. Run this again later to score the rest.")
            break
        continue
    if start + BATCH_SIZE < len(todo):
        time.sleep(13)

done = {a["url"] for a in scored}
leftover = [a for a in todo if a["url"] not in done]
if leftover and not out_of_quota and requests_made < REQUEST_BUDGET:
    print(f"{len(leftover)} articles were refused. Trying them once more in {SECOND_CHANCE_WAIT}s...")
    time.sleep(SECOND_CHANCE_WAIT)
    overloaded.clear()
    for start in range(0, len(leftover), BATCH_SIZE):
        if not score_and_record(leftover[start:start + BATCH_SIZE]):
            print("Still refused. They will be tried the next time Mimir opens.")
            break

if not scored:
    raise SystemExit("Nothing was scored, so scored.json was left untouched.")

PRIMARY = MODELS[0]
provisional = [a for a in scored if a.get("scored_by") and a["scored_by"] != PRIMARY
               and not a.get("merged_into")]
if provisional and PRIMARY not in overloaded and PRIMARY not in exhausted:
    print(f"{len(provisional)} articles have provisional scores from a fallback model. "
          f"Trying {PRIMARY} for them...")
    upgraded = 0
    for start in range(0, len(provisional), BATCH_SIZE):
        batch = provisional[start:start + BATCH_SIZE]
        scores = score_batch(batch, SUMMARY_CHARS, models=[PRIMARY])
        if not scores:
            print("The primary model is busy again, so the rest keep their provisional "
                  "scores until a later run.")
            break
        for item in scores:
            if 0 <= item["id"] < len(batch):
                article = batch[item["id"]]
                article["significance"] = item["score"]
                article["significance_reason"] = item["reason"]
                article["category"] = item["category"]
                article["scored_by"] = PRIMARY
                article["prompt_version"] = PROMPT_VERSION
                upgraded += 1
    print(f"Upgraded {upgraded} of {len(provisional)} provisional scores.")
elif provisional:
    print(f"{len(provisional)} articles have provisional scores from a fallback model. "
          f"They will be re-scored when {PRIMARY} is free.")


def rank(article):
    return (article["significance"], article.get("coverage_count") or 1,
            article.get("time_published") or "")


def set_aside(article, reason):
    article["category_claimed"] = article.get("category")
    article["category"] = "none"
    article["significance"] = min(article["significance"], 2)
    article["significance_reason"] = reason


guarded = 0
for article in scored:
    category = article.get("category") or "none"
    if category != "none" and not article.get("merged_into") and not categories.fits(article, category):
        if categories.SOURCE.get(category) != article.get("feed"):
            set_aside(article, f"Filed under {category}, which takes its stories from another source.")
        else:
            set_aside(article, f"Filed under {category} without ever mentioning it.")
        guarded += 1
if guarded:
    print(f"The category check set aside {guarded} articles that cannot stand in the category they were filed under.")


def finalists():
    picked = []
    for category in CATEGORY_KEYS:
        pool = sorted((a for a in scored if a.get("category") == category
                       and a["significance"] >= MIN_SCORE and not a.get("merged_into")),
                      key=rank, reverse=True)[:FINALISTS_PER_CATEGORY]
        picked += [a for a in pool if not (a.get("verify_version") == VERIFY_VERSION
                                           and a.get("verified_category") == category)]
    return picked


if overloaded and finalists():
    time.sleep(VERIFY_WAIT)
    overloaded.clear()

for _ in range(2):
    batch = finalists()
    if not batch or out_of_quota or requests_made >= REQUEST_BUDGET:
        break
    print(f"Checking {len(batch)} finalists...")
    lines = [f"id {i} | filed under {a['category']} | {a['source']} | {a['title']} | "
             f"{a['summary'][:400]}" for i, a in enumerate(batch)]
    verdicts = ask("\n".join(lines), len(batch), VERIFY_PROMPT, list[Verdict])
    if not verdicts:
        print("Could not check the finalists this time; they are shown unchecked.")
        break

    by_id = {v["id"]: v for v in verdicts if 0 <= v["id"] < len(batch)}
    moved = removed = 0
    for i, article in enumerate(batch):
        verdict = by_id.get(i)
        if not verdict:
            continue
        filed, actual = article["category"], verdict["category"]
        article["verify_reason"] = verdict["reason"]
        if actual == filed:
            pass
        elif actual in CATEGORY_KEYS and categories.fits(article, actual):
            article["category_claimed"] = filed
            article["category"] = actual
            moved += 1
        else:
            set_aside(article, verdict["reason"])
            removed += 1
        article["verify_version"] = VERIFY_VERSION
        article["verified_category"] = article["category"]

    for i, article in enumerate(batch):
        j = by_id.get(i, {}).get("same_event_as", -1)
        if not 0 <= j < len(batch) or j == i:
            continue
        other = batch[j]
        if "none" not in (article["category"], other["category"]) and article["category"] != other["category"]:
            weaker, stronger = sorted((article, other), key=rank)
            set_aside(weaker, "Same event as the lead story in another category.")
            weaker["duplicate_of"] = stronger["url"]
            removed += 1

    print(f"Checked {len(batch)}: {len(batch) - moved - removed} confirmed, {moved} moved to "
          f"a better category, {removed} set aside.")


def article_text(article):
    link = article.get("article_url") or article["url"]
    return "" if pages.is_google_news(link) else pages.read_text(link)


def unexplained():
    picked = []
    for category in CATEGORY_KEYS:
        pool = sorted((a for a in scored if a.get("category") == category
                       and a["significance"] >= MIN_SCORE and not a.get("merged_into")),
                      key=rank, reverse=True)[:FINALISTS_PER_CATEGORY]
        picked += [a for a in pool if a.get("explain_version") != EXPLAIN_VERSION]
    return picked


to_explain = unexplained()
if to_explain and not out_of_quota and requests_made < REQUEST_BUDGET:
    print(f"Writing explanations for {len(to_explain)} stories...")
    with ThreadPoolExecutor(8) as pool:
        texts = list(pool.map(article_text, to_explain))
    lines = [f"id {i} | {a['category']} | {a['source']} | {a['title']}\n"
             f"summary: {a['summary'][:400]}"
             + (f"\narticle text: {text[:ARTICLE_CHARS]}" if text else "")
             for i, (a, text) in enumerate(zip(to_explain, texts))]
    explanations = ask("\n\n".join(lines), len(to_explain), EXPLAIN_PROMPT, list[Explanation])
    if explanations:
        written = 0
        for item in explanations:
            if 0 <= item["id"] < len(to_explain) and item["explainer"].strip():
                to_explain[item["id"]]["explainer"] = item["explainer"].strip()
                to_explain[item["id"]]["explain_version"] = EXPLAIN_VERSION
                written += 1
        print(f"Wrote {written} explanations.")
    else:
        print("Could not write the explanations this time; the next run will try again.")


scored.sort(key=rank, reverse=True)
briefing = [a for a in scored if a["significance"] >= MIN_SCORE]

with open(paths.data("scored.json"), "w") as f:
    json.dump(scored, f, indent=2)

with open(paths.data("briefing_data.js"), "w") as f:
    f.write("window.MIMIR_DATA = ")
    json.dump(scored, f)
    f.write(";\n")

print(f"Scored {len(scored)} of {len(articles)} articles; "
      f"{len(briefing)} scored {MIN_SCORE} or above. Top 15:")
for article in briefing[:15]:
    print(f"{article['significance']:>2}  x{article['coverage_count']}  [{article['topic']}] {article['title']}")
