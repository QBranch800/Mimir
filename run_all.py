"""Run the whole Mimir pipeline in order.

The fetch steps are optional: if one source is rate limited or its key is missing,
the run carries on with whatever the others returned. Filtering and
scoring are required, because without them there is no briefing to show.
"""

import os
import subprocess
import sys
import time

PYTHON = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))

# (script, label, required)
STEPS = [
    ("fetch_rss.py",     "Monetary policy feeds",     False),
    ("fetch_news.py",    "Alpha Vantage headlines",   False),
    ("fetch_gdelt.py",   "GDELT geopolitics",         False),
    ("filter_news.py",   "Filtering and deduping",    True),
    ("score_news.py",    "Scoring with Gemini",       True),
]


def run(script, label):
    print(f"\n\033[1m{label}\033[0m  ({script})")
    print("-" * 60)
    started = time.time()
    result = subprocess.run([PYTHON, os.path.join(HERE, script)], cwd=HERE)
    seconds = time.time() - started
    print(f"-- {'ok' if result.returncode == 0 else 'failed'} in {seconds:.0f}s")
    return result.returncode == 0


def main():
    print("Running the Mimir pipeline. This takes a few minutes, mostly waiting "
          "out rate limits.")
    failed = []

    for script, label, required in STEPS:
        if not os.path.exists(os.path.join(HERE, script)):
            print(f"\nSkipping {script}: file not found.")
            failed.append(label)
            continue

        if run(script, label):
            continue

        failed.append(label)
        if required:
            print(f"\n{label} failed, so there is nothing to show. Stopping here.")
            return 1
        print(f"{label} failed. Carrying on with the other sources.")

    print("\n" + "=" * 60)
    if failed:
        print("Finished, but these steps did not complete: " + ", ".join(failed))
        print("The briefing is built from whatever did work.")
    else:
        print("Finished. Every step completed.")
    print("Open index.html to read the briefing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
