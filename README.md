# Mimir

A daily briefing app that surfaces genuinely market-moving news across five fixed categories: monetary policy, US fiscal policy, US macroeconomic data, geopolitics, and tech and AI. It filters out the routine single-stock noise that fills most financial feeds.

## Status

Early development, but usable end to end. It fetches headlines from Alpha Vantage and NewsAPI, removes duplicates and known noise, scores what is left for significance with Gemini across the five categories, and shows the leading story in each as a briefing you read in the browser. A local server adds a refresh button, somewhere to keep your API keys, and a daily schedule.

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

That runs the four steps below in order. If a news source is rate limited or missing a key the
run carries on with the others, but it stops if filtering or scoring fails, since there would
be no briefing to show. The individual steps can still be run on their own:

1. `fetch_news.py` fetches headlines from Alpha Vantage into `results.json`. The free tier
   allows about 25 requests a day, so avoid re-running it needlessly.
2. `fetch_newsapi.py` fetches geopolitics headlines from NewsAPI for the last two days into
   `newsapi_results.json`. The free tier allows 100 requests a day; a run uses four.
3. `filter_news.py` merges both sources into `filtered.json`. It drops blocked sources,
   noisy titles and recurring market roundups, keeps geopolitics articles only from an
   allowlist of trusted outlets, and merges near-duplicate titles while counting how many
   outlets covered each story.
4. `score_news.py` asks Gemini to rate each article from 1 to 10 against five categories:
   monetary policy, US fiscal policy, US macroeconomic data, geopolitics, and tech and AI. It
   tags each article with the category it belongs to, fetches the page text for the top
   articles that have no summary and scores those again, then writes `scored.json`.

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

### Keeping it up to date by itself

Mimir schedules its own refresh rather than relying on cron, launchd or Task Scheduler, so it
behaves the same on macOS, Windows, Linux and a hosted deployment. It refreshes on two triggers: when it
starts up, if the briefing was not built today, and once a day at a time you choose in
Settings while it keeps running. The first covers opening the app fresh each morning, the
second covers a hosted deployment or an app left open, where startup happened long ago. If Gemini refuses a request it tries
again a few times over the morning, which costs little because scoring is incremental.

The default slot is shortly after Gemini's free daily allowance resets, worked out in your own
timezone. The one thing the app cannot do is schedule itself while it is not running, so for a
briefing that is ready before you open anything, either leave `app.py` running, start it at
login, or host it somewhere that stays up.

Either way, the briefing shows the single most significant story in each category, with a
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
- [x] Add geopolitical coverage from NewsAPI
- [x] Read the briefing as a page, one leading story per category
- [x] Settings: theme, significance threshold, category choice and order
- [x] Run the whole pipeline with one command
- [x] Refresh the briefing and save API keys from the page, via a local server
- [x] Refresh on a schedule, the same way on every OS and in a hosted deployment
- [x] Package as a desktop app for macOS and Windows, built automatically on GitHub
- [ ] Sign and notarise the builds so they open without a security warning (needs a paid
      Apple Developer account, and a code signing certificate on Windows)