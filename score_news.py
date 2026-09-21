import json
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-3.6-flash"
BATCH_SIZE = 50
MAX_ATTEMPTS = 4
RETRY_CODES = {429, 503}

SYSTEM_PROMPT = """You rate news articles for a daily briefing aimed at investors who want
genuinely market-moving news across: US macroeconomics, US monetary policy, US fiscal policy,
geopolitics, and technology.

Score each article's significance from 1 to 10:
- 9-10: moves whole markets or the economy (central bank decisions, major economic data,
  major legislation or tariffs, wars or sanctions, systemic events)
- 6-8: important for a sector or sizeable group of companies, or a strong signal about the
  economy (big earnings surprises, major regulation, large deals)
- 3-5: relevant but routine or narrow (single-company news, analyst opinions, commentary)
- 1-2: noise (press releases, marketing, product announcements, stock tips, filings)

Give a one-sentence reason for each score. Return one entry per article, using the id given."""


class Score(BaseModel):
    id: int
    score: int
    reason: str


with open("filtered.json") as f:
    articles = json.load(f)

scored = []
for start in range(0, len(articles), BATCH_SIZE):
    batch = articles[start:start + BATCH_SIZE]
    print(f"Scoring articles {start + 1}-{start + len(batch)} of {len(articles)}...")

    lines = []
    for i, article in enumerate(batch):
        lines.append(f"id {i} | {article['source']} | {article['title']} | {article['summary'][:300]}")

    scores = None
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
            scores = json.loads(response.text)
            break
        except Exception as e:
            retryable = getattr(e, "code", None) in RETRY_CODES
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                print(f"Batch failed: {e}")
                break
            wait = 10 * 2 ** attempt
            print(f"Error {e.code}, retrying in {wait}s (attempt {attempt + 2} of {MAX_ATTEMPTS})...")
            time.sleep(wait)

    if scores is None:
        continue

    for item in scores:
        if 0 <= item["id"] < len(batch):
            article = batch[item["id"]]
            article["significance"] = item["score"]
            article["significance_reason"] = item["reason"]
            scored.append(article)

    time.sleep(13)

if not scored:
    raise SystemExit("Nothing was scored, so scored.json was left untouched.")

scored.sort(key=lambda a: a["significance"], reverse=True)

with open("scored.json", "w") as f:
    json.dump(scored, f, indent=2)

print(f"Scored {len(scored)} of {len(articles)} articles. Top 15:")
for article in scored[:15]:
    print(f"{article['significance']:>2}  [{article['topic']}] {article['title']}")
