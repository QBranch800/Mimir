# Mimir

A daily briefing app that surfaces significant market-moving news across macroeconomics, US monetary policy, US fiscal policy, geopolitics, and a user-selected industry filtering out routine single-stock noise to focus on genuinely significant events.

## Status

Early development. Currently fetches and displays raw headlines per category from Alpha Vantage's News & Sentiment API. Significance filtering, a web interface, and industry selection are not yet built.

## Setup

1. Clone this repo
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip3 install -r requirements.txt`
5. Copy `.env.example` to `.env` and add your own Alpha Vantage API key (free at alphavantage.co)

## Running it


## Roadmap

- [x] Fetch headlines from Alpha Vantage across multiple topics
- [ ] Filter headlines for genuine significance (not just topic-tag relevance)
- [ ] Add geopolitical coverage via a second source (GDELT)
- [ ] Build a web interface with category tabs and an industry dropdown
- [ ] Wrap as a desktop app with Electron
- [ ] Optional: AI-assisted significance scoring (Gemini API)