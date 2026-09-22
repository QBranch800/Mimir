# Mimir

A daily briefing app that surfaces significant market-moving news across macroeconomics, US monetary policy, US fiscal policy, geopolitics, and a user-selected industry filtering out routine single-stock noise to focus on genuinely significant events.

## Status

Early development. Currently fetches headlines per category from Alpha Vantage's News & Sentiment API, removes duplicates and known noise, and scores the rest for significance with Gemini. A web interface and industry selection are not yet built.

## Setup

1. Clone this repo
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip3 install -r requirements.txt`
5. Copy `.env.example` to `.env` and add your own API keys, all free:
   - Alpha Vantage, at alphavantage.co
   - Gemini, at aistudio.google.com
   - NewsAPI, at newsapi.org

## Running it

With the virtual environment activated, run everything with one command:

```
python3 run_all.py
```

That runs the five steps below in order. If a news source is rate limited or missing a key the
run carries on with the others, but it stops if filtering or scoring fails, since there would
be no briefing to show. The individual steps can still be run on their own:

1. `fetch_news.py` fetches headlines from Alpha Vantage into `results.json`. The free tier
   allows about 25 requests a day, so avoid re-running it needlessly.
2. `fetch_gdelt.py` fetches geopolitics headlines from GDELT (no API key needed) into
   `gdelt_results.json`. GDELT rate limits aggressively and the script backs off and retries.
3. `fetch_newsapi.py` fetches geopolitics headlines from NewsAPI for the last two days into
   `newsapi_results.json`. The free tier allows 100 requests a day; a run uses four.
4. `filter_news.py` merges all three sources into `filtered.json`. It drops blocked sources,
   noisy titles and recurring market roundups, keeps geopolitics articles only from an
   allowlist of trusted outlets, and merges near-duplicate titles while counting how many
   outlets covered each story.
5. `score_news.py` asks Gemini to rate each article from 1 to 10 against five categories:
   monetary policy, US fiscal policy, US macroeconomic data, geopolitics, and tech and AI. It
   tags each article with the category it belongs to, fetches the page text for the top
   articles that have no summary and scores those again, then writes `scored.json`. The Gemini
   free tier allows 20 requests a day and a run uses two.

## Reading the briefing

Open `index.html` in a browser. The briefing shows the single most significant story in each
category, with a reading pane beside it. Settings has a theme switch, a significance
threshold, control over which categories appear and in what order, and a way to clear saved
stories.

Opening the file directly works, because `score_news.py` also writes the data as
`briefing_data.js` for that case. If you would rather serve it, run `python3 -m http.server
8000` in this folder and open `http://localhost:8000`.

## Roadmap

- [x] Fetch headlines from Alpha Vantage across multiple topics
- [x] Filter out duplicates and known noise (source blocklist and title patterns)
- [x] AI-assisted significance scoring (Gemini API)
- [x] Add geopolitical coverage from GDELT and NewsAPI
- [x] Read the briefing as a page, one leading story per category
- [x] Settings: theme, significance threshold, category choice and order
- [x] Run the whole pipeline with one command
- [ ] Let the page trigger a fetch and re-score itself, rather than only showing the last run
- [ ] Add an industry dropdown
- [ ] Wrap as a desktop app with Electron