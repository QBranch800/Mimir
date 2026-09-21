# Mimir

A daily briefing app that surfaces significant market-moving news across macroeconomics, US monetary policy, US fiscal policy, geopolitics, and a user-selected industry filtering out routine single-stock noise to focus on genuinely significant events.

## Status

Early development. Currently fetches headlines per category from Alpha Vantage's News & Sentiment API, removes duplicates and known noise, and scores the rest for significance with Gemini. A web interface and industry selection are not yet built.

## Setup

1. Clone this repo
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip3 install -r requirements.txt`
5. Copy `.env.example` to `.env` and add your own Alpha Vantage API key (free at alphavantage.co) and Gemini API key (free at aistudio.google.com)

## Running it

With the virtual environment activated, run these in order:

1. `python3 fetch_news.py` fetches headlines and saves them to `results.json`. The Alpha Vantage free tier allows about 25 requests a day, so avoid re-running it needlessly.
2. `python3 fetch_gdelt.py` fetches geopolitics headlines from GDELT (no API key needed) and saves them to `gdelt_results.json`. GDELT limits requests to one every 5 seconds, so the script retries if it gets rate-limited.
3. `python3 filter_news.py` merges both sources and saves `filtered.json`. It removes blocked sources and noisy titles, keeps GDELT geopolitics articles only from an allowlist of trusted outlets, and merges near-duplicate titles while counting how many outlets covered each story.
4. `python3 score_news.py` asks Gemini to rate each article's significance from 1 to 10 based on its title. It then downloads the page text for the top 20 articles that have no summary and scores those again. Same-story articles are merged, anything scoring below 4 is dropped, and the rest is saved to `scored.json`, with the top 15 printed.

## Roadmap

- [x] Fetch headlines from Alpha Vantage across multiple topics
- [x] Filter out duplicates and known noise (source blocklist and title patterns)
- [x] AI-assisted significance scoring (Gemini API)
- [x] Add geopolitical coverage via a second source (GDELT)
- [ ] Build a web interface with category tabs and an industry dropdown
- [ ] Wrap as a desktop app with Electron