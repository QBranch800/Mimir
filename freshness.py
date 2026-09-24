"""Deciding whether the briefing needs refreshing when Mimir opens.

There is no timer. Mimir refreshes when you open it and the briefing is not from today,
finishes the job when an earlier run today was cut short, and otherwise only refreshes
when you press Refresh. A daily timer inside the app could only fire
while the app happened to be running, which in practice meant it rarely did.

Nothing here looks at the clock on its own: `needs_refresh` is given the time and the
saved state and answers yes or no, which keeps it easy to test.
"""

import datetime
import json
import os
import zoneinfo

import paths

STATE_PATH = paths.data("refresh.json")

# Gemini's free tier resets its daily allowance at midnight US Pacific.
QUOTA_TZ = "America/Los_Angeles"


def quota_reset_local(now=None):
    """The local wall-clock time at which the Gemini daily allowance next resets."""
    now = now or datetime.datetime.now().astimezone()
    now_pacific = now.astimezone(zoneinfo.ZoneInfo(QUOTA_TZ))
    midnight = (now_pacific + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(now.tzinfo)


def load():
    """Returns (enabled, state). A missing or damaged file just means the defaults."""
    enabled, state = True, {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                enabled = bool(stored.get("enabled", True))
                if isinstance(stored.get("state"), dict):
                    state = stored["state"]
        except (ValueError, OSError):
            pass
    return enabled, state


def save(enabled, state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"enabled": enabled, "state": state}, f, indent=2)
    os.replace(tmp, STATE_PATH)        # never leave a half written file behind


def needs_refresh(enabled, state, data_mtime, now, unfinished=0):
    """What opening the app should do. Returns (action, reason for the page).

    action is "full" to fetch and score, "finish" to only score articles an earlier run
    today could not get to, or None to leave the briefing alone. Finishing never fetches
    again, so it does not spend the news sources' daily allowances.
    """
    if not enabled:
        return None, "Refreshing on open is off. Use Refresh now when you want one."

    blocked_until = state.get("blocked_until") or 0
    if now.timestamp() < blocked_until:
        when = datetime.datetime.fromtimestamp(blocked_until, now.tzinfo)
        return None, (f"Gemini is out of requests until {when:%H:%M}, so the briefing was "
                      f"not refreshed. Open Mimir again after that, or press Refresh now.")

    if not data_mtime:
        return "full", "Building your first briefing."

    # a daily briefing: what matters is whether it was built today, not how many hours
    # old it is, so one built at 20:00 yesterday is stale when you open it at 09:00
    built = datetime.datetime.fromtimestamp(data_mtime, now.tzinfo)
    if built.date() < now.date():
        return "full", "The briefing was from an earlier day, so it is being refreshed."
    if unfinished:
        return "finish", (f"Scoring the {unfinished} articles an earlier run today could "
                          f"not get to.")
    return None, f"Today's briefing, built at {built:%H:%M}."


def record_result(state, now, ok, hit_daily_quota=False):
    if ok:
        state["last_success"] = now.timestamp()
        state["blocked_until"] = 0
    elif hit_daily_quota:
        # opening the app again before the reset would only fail the same way
        state["blocked_until"] = quota_reset_local(now).timestamp()
    return state
