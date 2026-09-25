# Mimir

A daily briefing app that surfaces genuinely market-moving news across five fixed categories: monetary policy, US fiscal policy, US macroeconomic data, geopolitics, and tech and AI. It filters out the routine single-stock noise that fills most financial feeds.

## Status

Early development, but usable end to end. Each category draws on one source: central bank and news desk RSS feeds for monetary policy, Alpha Vantage for US fiscal policy, US macro data and tech and AI, and GDELT for geopolitics. It strictly filters what they return down to at most ten stories per category, scores those for significance with Gemini, and shows the leading story in each as a briefing you read in the browser. A local server adds a refresh button and somewhere to keep your API keys, and the briefing refreshes itself when you open the app.

## Setup

1. Clone this repo
2. Create a virtual environment: `python3 -m venv venv`
3. Activate it: `source venv/bin/activate`
4. Install dependencies: `pip3 install -r requirements.txt`
5. Copy `.env.example` to `.env` and add your own API keys, both free:
   - Alpha Vantage, at alphavantage.co
   - Gemini, at aistudio.google.com

   The RSS feeds and GDELT need no key.

## Running it

With the virtual environment activated, run everything with one command:

```
python3 run_all.py
```

That runs the five steps below in order. If a news source is rate limited or missing a key the
run carries on with the others, but it stops if filtering or scoring fails, since there would
be no briefing to show. The individual steps can still be run on their own:

1. `fetch_rss.py` fetches monetary policy from the Federal Reserve, the ECB and the Bank of
   England, and from the CNBC, Guardian, BBC and NPR news desks that report on central
   banks, into `rss_results.json`. It needs no API key, and its stories are minutes old.
2. `fetch_news.py` fetches US fiscal policy, US macro data and tech and AI headlines from
   Alpha Vantage for the last 36 hours into `results.json`. The free tier allows 25 requests
   a day; a run uses three.
3. `fetch_gdelt.py` fetches geopolitics from GDELT's raw event files for the last 24 hours
   into `gdelt_results.json`. It keeps events between two countries, or involving a body such
   as the UN, reported by outlets on an allowlist, ranks the articles by how widely their
   events were reported, and reads the headline and summary of the top 20. It needs no key.
4. `filter_news.py` merges all three into `filtered.json`, strictly, since every story it
   passes on costs part of a Gemini request. It drops anything more than 36 hours old, known
   sources of stock filler, noisy titles and recurring market roundups, and any story that is
   not plainly about a category its source was chosen for, judged by that category's own
   words. It merges near-duplicate titles, then keeps at most ten stories per category, the
   ones carried by the most outlets, so a whole day normally fits in one Gemini request.
5. `score_news.py` asks Gemini to rate each article from 1 to 10 against five categories:
   monetary policy, US fiscal policy, US macroeconomic data, geopolitics, and tech and AI. It
   tags each article with the category it belongs to, fetches the page text for the top
   articles that have no summary and scores those again, then checks its own work before
   writing `scored.json`:
   - a story filed under a category whose source it did not come from, or under monetary
     policy, fiscal policy or macro data without ever using that category's own vocabulary,
     is set aside as a misfile
   - the few stories the briefing will actually show are checked again in one small request,
     which can confirm them, move them to a better category, or set them aside, and which
     keeps the same event from leading two categories at once

   It uses `gemini-3.5-flash-lite`. If that is overloaded it falls back to
   `gemini-3.1-flash-lite`, which has its own free allowance. Those scores are marked
   provisional and scored again by the main model when it is free.

   Scoring is incremental: an article that already has a score in `scored.json` is left alone,
   so only new articles cost anything. If Gemini refuses a batch, those articles simply stay
   unscored and the next run picks them up, rather than the work being lost. Running it twice
   in a row is therefore cheap, and running it after a failed attempt is the way to finish the
   job. The free tier allows 20 requests a day and resets at midnight US Pacific time, which
   may not be midnight where you are.

## Reading the briefing

The best way is to run the local server:

```
python3 app.py
```

then open `http://127.0.0.1:5111`. As well as the briefing, this gives you a Refresh button
that runs the pipeline from the page, and somewhere to paste your API keys instead of editing
`.env` by hand. It listens on localhost only: it can run the pipeline and write your keys, so
it is not something to expose to a network. Set `PORT` to use a different port. It avoids
port 5000 because macOS answers that with its AirPlay receiver.

You can also just open `index.html` from the file system. `score_news.py` writes the data as
`briefing_data.js` so that works with no server; refreshing and key entry are the only things
that need `app.py`.

### Keeping it up to date

When you open Mimir and the briefing is not from today, it builds a new one. There is no timer,
so nothing runs while Mimir is closed, and a refresh never happens behind your back. You can
also press Refresh in Settings at any time, or switch refreshing on open off there.

A refresh takes a minute or two, during which the previous briefing stays on screen. If you
would rather it was ready the moment you look, add Mimir to your Login Items (macOS) or Startup
folder (Windows), so it opens and refreshes when the computer starts.

If Gemini is out of requests for the day, Mimir says so and does not try again until the
allowance resets, since opening the app again before then would only fail the same way.

The briefing shows the single most significant story in each category, with a
reading pane beside it. Settings has a theme switch, a significance threshold, control over
which categories appear and in what order, and a way to clear saved stories.

## As a desktop app

### Getting a build

Ready-made builds are on the [releases page](https://github.com/QBranch800/Mimir/releases).

Pushing a `v*` tag builds both and publishes them there. Running **Build desktop apps** from
the Actions tab builds them without publishing, leaving the zips attached to that run for two
weeks. Either way they are built on a real Mac and a real Windows machine, because PyInstaller
cannot cross compile. To
build just for yourself on the machine you are sitting at, run `python3 build_desktop.py`.

### Opening it the first time

Neither build is signed with a paid developer certificate, so both systems will warn about it
once. This is about the app being unrecognised, not about anything being wrong with it.

- **macOS:** double-clicking shows "Apple could not verify Mimir is free of malware", offering
  only Move to Trash and Done. Click **Done**, then open **System Settings > Privacy &
  Security**, scroll to Security, and click **Open Anyway** next to the note about Mimir.
  Authenticate, then confirm **Open**. After that it launches normally.

  Control-clicking and choosing Open used to work and no longer does: Apple removed that
  bypass in macOS 15, so System Settings is the only route on current versions. The Open
  Anyway button appears for about an hour after a blocked attempt; if it is gone, double-click
  the app again to bring it back.
- **Windows:** SmartScreen shows "Windows protected your PC". Choose More info, then Run
  anyway.

### Where your data lives

Keys, fetched news and settings are kept in the folder your system uses for application data,
not inside the app, so updating or reinstalling never wipes them:

- macOS: `~/Library/Application Support/Mimir`
- Windows: `%APPDATA%\Mimir`

Set `MIMIR_DATA_DIR` to put them somewhere else. Every run also writes `run.log` there, which
is the first place to look if a refresh did not do what you expected.

On first run the app asks for your API keys rather than showing an empty briefing.

## Roadmap

- [x] Fetch headlines from Alpha Vantage across multiple topics
- [x] Filter out duplicates and known noise (source blocklist and title patterns)
- [x] AI-assisted significance scoring (Gemini API)
- [x] Add geopolitical coverage from GDELT
- [x] One source per category, filtered to at most ten stories each before scoring
- [x] Read the briefing as a page, one leading story per category
- [x] Settings: theme, significance threshold, category choice and order
- [x] Run the whole pipeline with one command
- [x] Refresh the briefing and save API keys from the page, via a local server
- [x] Refresh when the app opens, if the briefing is not from today
- [x] Package as a desktop app for macOS and Windows, built automatically on GitHub
- [ ] Sign and notarise the builds so they open without a security warning (needs a paid
      Apple Developer account, and a code signing certificate on Windows)