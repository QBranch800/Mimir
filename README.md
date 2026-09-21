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
2. `python3 filter_news.py` removes duplicates, blocked sources and noisy titles, and saves `filtered.json`.
3. `python3 score_news.py` asks Gemini to rate each remaining article's significance from 1 to 10, saves `scored.json`, and prints the top 15.

## Roadmap

- [x] Fetch headlines from Alpha Vantage across multiple topics
- [x] Filter out duplicates and known noise (source blocklist and title patterns)
- [x] AI-assisted significance scoring (Gemini API)
- [ ] Add geopolitical coverage via a second source (GDELT)
- [ ] Build a web interface with category tabs and an industry dropdown
- [ ] Wrap as a desktop app with Electron