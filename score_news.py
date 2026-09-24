import hashlib
import json
import os
import time
import requests
import trafilatura
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

import categories
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

# Tried in order. The full Flash model scores best, but it has refused batches with
# 503 "high demand" on most days, when the lighter flash-lite models answered the same
# 50 article batch in a few seconds. Falling back keeps a run from failing outright.
# Gemini counts its free daily allowance per model, so each fallback also has its own
# 20 requests rather than sharing the first model's.
MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# Not one big batch. A 134 article request was refused with 503 "high demand" over and
# over while a 5 article one to the same model went through seconds later, so large
# requests get shed when the service is busy, whatever the token limits allow. Batches
# of this size have been served reliably. The cost is that Gemini can only merge
# duplicate stories within a batch, so the same story in two batches stays twice.
BATCH_SIZE = 50
MAX_ATTEMPTS = 3
RETRY_CODES = {429}          # 503 is handled separately: it is not worth retrying
# Every call counts against its model's 20 a day, including ones the server fails.
# A clean run costs four: three batches for ~135 articles, plus the second pass. When
# the first model is overloaded each batch costs one extra request to find a free one,
# so this allows for that without letting a bad day run away with the allowance.
REQUEST_BUDGET = 16
# Gemini's refusals come and go within minutes. Before giving up on articles, and before
# the finalist check, wait this long and give every model one more chance.
SECOND_CHANCE_WAIT = 30
VERIFY_WAIT = 20
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
- "L3Harris awarded $876 million Navy contract" is one company winning a contract. It is
  "none", not US fiscal policy, however large the sum.
- "Medicare lab fee changes hit BillionToOne and CareDx" is about two companies' revenue. It is
  "none". A rule change reported as its effect on named companies is a company story.
- "Why is X stock surging premarket?" is a share price move. It is always "none".
The same story told the other way round does belong: "US and China agree agricultural
concessions at summit" is geopolitics, because the agreement is the subject.

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


# A score only means something under the prompt that produced it. Stamping each one
# with a fingerprint of the prompt means tuning the prompt automatically redoes the
# stale scores, rather than someone having to remember to clear them by hand.
PROMPT_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]


CATEGORY_KEYS = ["monetary_policy", "us_fiscal_policy", "us_macro_data", "geopolitics",
                 "tech_and_ai"]

# A second, much smaller request that checks only the stories the briefing will actually
# show. The lighter models misfile stories when judging fifty at once, but get the same
# stories right when judging a handful, so the check is cheap and catches what matters.
VERIFY_PROMPT = """You check the finalists of a daily market briefing before anyone reads
them. Each line gives an article and the category it was filed under. Say which category
the article genuinely belongs to: usually the one it was filed under, sometimes another,
often none.

- monetary_policy: central banks setting interest rates, guidance, balance sheets or money
  itself (the Fed, ECB, Bank of England, Bank of Japan and their peers). Commercial banks,
  even building money-like products, are not monetary policy.
- us_fiscal_policy: the US federal government's budget, taxes, spending and debt (Congress,
  the Treasury, the White House budget). Not states, cities, utilities or fee schedules.
- us_macro_data: US economic releases and what they show: CPI, jobs, GDP, PMI, retail sales.
- geopolitics: conflicts, sanctions, elections, trade policy and diplomacy with economic or
  market weight.
- tech_and_ai: technology with economic weight: AI capability or infrastructure, chips and
  their supply, large data centre or chip plant investment, tech regulation and antitrust.

The answer is "none" when the article is really about one company (its shares, valuation,
earnings, analyst ratings, contracts, products or prospects), even if it names a policy, a
war or a data release as background. It is also "none" when the article only nearly fits.
When unsure, say none: the briefing would rather show nothing in a category than something
wrong.

If two articles report the same event, set same_event_as on the later one to the id of the
earlier one. Otherwise set it to -1.

Give a one-sentence reason. Return one entry per article, using the id given."""

VERIFY_VERSION = hashlib.sha256(VERIFY_PROMPT.encode()).hexdigest()[:12]
FINALISTS_PER_CATEGORY = 3   # the leader plus two in reserve, in case the leader fails


class Verdict(BaseModel):
    id: int
    category: str
    same_event_as: int
    reason: str


class Score(BaseModel):
    id: int
    score: int
    reason: str
    story_id: int
    category: str


requests_made = 0
out_of_quota = False
exhausted = set()            # models that have run out of today's allowance
overloaded = set()           # models that refused with 503 earlier in this run
last_model = None            # which model answered the most recent batch


def is_daily_quota(error):
    """A daily quota 429 cannot recover during this run, unlike a per-minute one."""
    text = str(error)
    return "429" in text and ("PerDay" in text or "per day" in text)


def score_batch(batch, chars, models=None):
    """Score one batch, falling back through MODELS when one is overloaded or spent.

    Pass models to restrict which are tried: upgrading a provisional score only makes
    sense with the primary, so falling back there would just redo the same work.
    """
    lines = []
    for i, article in enumerate(batch):
        lines.append(
            f"id {i} | {article['source']} | {article['coverage_count']} outlet(s) | "
            f"{article['title']} | {article['summary'][:chars]}"
        )
    return ask("\n".join(lines), len(batch), SYSTEM_PROMPT, list[Score], models)


def ask(contents, size, system, schema, models=None):
    """Send one request through the model chain. Returns the parsed reply, or None."""
    global out_of_quota, last_model

    for model in (models or MODELS):
        # an overload lasts minutes, so once a model has refused, skip it for the rest
        # of the run instead of paying a request per batch to hear the same answer
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
    """Returns the scores, None to give up on the batch, or "next" to try another model."""
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
            # this model's allowance is spent, but the others each have their own
            if is_daily_quota(e):
                exhausted.add(model)
                print(f"{model} is out of requests for today, trying the next model.")
                return "next"
            code = getattr(e, "code", None)
            # Shedding load tends to last minutes, so retrying the same model just
            # spends requests on a wall. A lighter model is usually free.
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
            loaded = [a for a in json.load(f) if "significance" in a]
        previous = {a["url"]: a for a in loaded if a.get("prompt_version") == PROMPT_VERSION}
        stale = len(loaded) - len(previous)
        if stale:
            print(f"{stale} articles were scored under an earlier version of the prompt, "
                  f"so they will be scored again.")
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

# Gemini can only spot two reports of the same story when they sit in the same batch, so
# put each topic's articles next to each other rather than in fetch order.
todo.sort(key=lambda a: a.get("topic") or "")

def score_and_record(batch):
    """Score one batch and add the results to `scored`. Returns False if it was refused."""
    scores = score_batch(batch, TITLE_STAGE_CHARS)
    if scores is None:
        return False

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
        best["scored_by"] = last_model
        best["prompt_version"] = PROMPT_VERSION
        for _, other in members:
            if other is not best:
                best["coverage_count"] += other["coverage_count"]
                best["also_covered_by"] += [other["source"]] + other["also_covered_by"]
        best["also_covered_by"] = sorted(set(best["also_covered_by"]))
        scored.append(best)
        # Record the ones folded into it. Leaving them out meant the next run saw them as
        # new, scored them alone in a small batch without their partner, and put the
        # duplicate straight back into the briefing.
        for _, other in members:
            if other is not best:
                other.update({"significance": 0, "category": "none", "merged_into": best["url"],
                              "significance_reason": "Same story as another article.",
                              "scored_by": last_model, "prompt_version": PROMPT_VERSION})
                scored.append(other)

    return True


# Stage 1: score from title (and summary where there is one)
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

# One more try for whatever was refused. Overloads pass, and without this a busy spell
# in the middle of a run left a third of the briefing for another day.
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

# Scores from a fallback model are provisional. The lighter models are much worse at
# the categorisation rules: they filed a Navy contract as fiscal policy and a share
# price move as geopolitics, which the full model does not. So whenever the primary is
# free, re-score those with it. Only the primary is tried here: falling back would just
# reproduce the provisional score, and the briefing already has that to show.
PRIMARY = MODELS[0]
provisional = [a for a in scored if a.get("scored_by") and a["scored_by"] != PRIMARY
               and not a.get("merged_into")]
if provisional and PRIMARY not in overloaded and PRIMARY not in exhausted:
    print(f"{len(provisional)} articles have provisional scores from a fallback model. "
          f"Trying {PRIMARY} for them...")
    upgraded = 0
    for start in range(0, len(provisional), BATCH_SIZE):
        batch = provisional[start:start + BATCH_SIZE]
        scores = score_batch(batch, TITLE_STAGE_CHARS, models=[PRIMARY])
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

# The second pass is an improvement, not a requirement, so skip it rather than spend
# requests we may not have. What was scored above is still saved either way. Only
# articles scored in this run are candidates; earlier ones have already had their turn.
fresh = {a["url"] for a in scored if a["url"] not in previous}
no_summary = [] if (out_of_quota or requests_made >= REQUEST_BUDGET) else \
    [a for a in scored if not a["summary"] and a["url"] in fresh and not a.get("merged_into")]
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
                article["scored_by"] = last_model
                article["prompt_version"] = PROMPT_VERSION


def rank(article):
    """Most significant first, then most widely covered, then the freshest."""
    return (article["significance"], article.get("coverage_count") or 1,
            article.get("time_published") or "")


def set_aside(article, reason):
    article["category_claimed"] = article.get("category")
    article["category"] = "none"
    article["significance"] = min(article["significance"], 2)
    article["significance_reason"] = reason


# Stage 3a: a free check. Monetary and fiscal stories almost always use their category's
# own vocabulary, so a story filed there that never does is a misfile.
guarded = 0
for article in scored:
    category = article.get("category") or "none"
    if category != "none" and not article.get("merged_into") and not categories.fits(article, category):
        set_aside(article, f"Filed under {category} without ever mentioning it.")
        guarded += 1
if guarded:
    print(f"The category check set aside {guarded} articles filed under a category they never mention.")


# Stage 3b: check the finalists, the few stories the briefing will actually show.
def finalists():
    picked = []
    for category in CATEGORY_KEYS:
        pool = sorted((a for a in scored if a.get("category") == category
                       and a["significance"] >= MIN_SCORE and not a.get("merged_into")),
                      key=rank, reverse=True)[:FINALISTS_PER_CATEGORY]
        picked += [a for a in pool if not (a.get("verify_version") == VERIFY_VERSION
                                           and a.get("verified_category") == category)]
    return picked


# This small request matters more than any other: it decides what is actually shown. A
# model skipped earlier for refusing a batch of fifty may well take a request this small.
if overloaded and finalists():
    time.sleep(VERIFY_WAIT)
    overloaded.clear()

for _ in range(2):           # a second round checks the reserves if leaders were set aside
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

    # the same event leading two categories would fill two of five slots with one story
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


scored.sort(key=rank, reverse=True)
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
