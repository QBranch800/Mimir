"""Deciding when Mimir should refresh itself.

The scheduler lives in the app rather than in the operating system, so the same code
works on macOS, Windows, Linux and a hosted web deployment. Nothing here starts a
thread or looks at the clock on its own: `should_run` is given the time and the saved
state and just answers yes or no, which makes it straightforward to test.

The catch with an in-app scheduler is that the app has to be running for its timer to
fire. `is_stale` covers the other case: when the app starts and the briefing is old,
refresh straight away instead of waiting for tomorrow's slot.
"""

import datetime
import json
import os
import zoneinfo

import paths

SCHEDULE_PATH = paths.data("schedule.json")

# Gemini's free tier resets its daily allowance at midnight US Pacific, so that is the
# moment a fresh run has the best chance of finishing.
QUOTA_TZ = "America/Los_Angeles"

DEFAULTS = {
    "enabled": True,
    "time": None,            # "HH:MM" local; None means "just after the quota resets"
    "retry_minutes": 20,     # how long to wait before trying again after a failure
    "max_attempts": 6,       # per day, so a bad morning cannot loop forever
    "stale_hours": 18,       # on startup, refresh if the briefing is older than this
}


def quota_reset_local(now=None):
    """The local wall-clock time at which the Gemini daily allowance resets."""
    now = now or datetime.datetime.now().astimezone()
    pacific = zoneinfo.ZoneInfo(QUOTA_TZ)
    now_pacific = now.astimezone(pacific)
    midnight = (now_pacific + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(now.tzinfo)


def default_time(now=None):
    """A sensible default slot: a little after the quota resets, in local time."""
    reset = quota_reset_local(now) + datetime.timedelta(minutes=15)
    return reset.strftime("%H:%M")


def load_schedule():
    cfg = dict(DEFAULTS)
    state = {}
    if os.path.exists(SCHEDULE_PATH):
        try:
            with open(SCHEDULE_PATH) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                for key in DEFAULTS:
                    if key in stored:
                        cfg[key] = stored[key]
                raw_state = stored.get("state")
                state = raw_state if isinstance(raw_state, dict) else {}
        except (ValueError, OSError):
            pass                       # a damaged file just means defaults
    if not cfg.get("time"):
        cfg["time"] = default_time()
    cfg["enabled"] = bool(cfg["enabled"])
    for key in ("retry_minutes", "max_attempts", "stale_hours"):
        try:
            cfg[key] = max(1, int(cfg[key]))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    return cfg, state


def save_schedule(cfg, state):
    payload = {key: cfg.get(key, DEFAULTS[key]) for key in DEFAULTS}
    payload["state"] = state
    tmp = SCHEDULE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, SCHEDULE_PATH)     # never leave a half written file behind


def slot_today(cfg, now):
    hour, _, minute = cfg["time"].partition(":")
    try:
        return now.replace(hour=int(hour), minute=int(minute),
                           second=0, microsecond=0)
    except ValueError:
        return now.replace(hour=6, minute=0, second=0, microsecond=0)


def attempts_today(state, now):
    return int(state.get("attempts", {}).get(now.date().isoformat(), 0))


def should_run(cfg, state, now):
    """Is a scheduled refresh due right now? Returns (bool, reason)."""
    if not cfg["enabled"]:
        return False, "Automatic refresh is off."

    blocked_until = state.get("blocked_until") or 0
    if now.timestamp() < blocked_until:
        when = datetime.datetime.fromtimestamp(blocked_until, now.tzinfo)
        return False, f"Out of Gemini requests. Waiting until {when:%H:%M}."

    slot = slot_today(cfg, now)
    if now < slot:
        return False, f"Next refresh at {slot:%H:%M}."

    if (state.get("last_success") or 0) >= slot.timestamp():
        return False, "Already refreshed since today's slot."

    tried = attempts_today(state, now)
    if tried >= cfg["max_attempts"]:
        return False, f"Tried {tried} times today without success. Waiting for tomorrow."

    last_attempt = state.get("last_attempt") or 0
    wait = cfg["retry_minutes"] * 60
    if last_attempt and now.timestamp() - last_attempt < wait:
        left = int((wait - (now.timestamp() - last_attempt)) / 60) + 1
        return False, f"Last attempt failed. Trying again in about {left} min."

    return True, "Due now."


def is_stale(data_mtime, cfg, now):
    """True when the briefing on disk is old enough to refresh on startup.

    This is a daily briefing, so what matters is whether it was built today rather
    than how many hours old it is: one built at 20:00 yesterday is still yesterday's
    news when you open the app at 09:00. The hours rule stays as a backstop for a very
    long session that crosses no startup.
    """
    if not cfg["enabled"]:
        return False
    if not data_mtime:
        return True                    # nothing has ever been built
    built = datetime.datetime.fromtimestamp(data_mtime, now.tzinfo)
    if built.date() < now.date():
        return True
    age_hours = (now.timestamp() - data_mtime) / 3600
    return age_hours >= cfg["stale_hours"]


def record_attempt(state, now):
    attempts = dict(state.get("attempts") or {})
    key = now.date().isoformat()
    attempts[key] = attempts.get(key, 0) + 1
    # keep only the last few days so the file does not grow forever
    for old in sorted(attempts)[:-5]:
        attempts.pop(old, None)
    state["attempts"] = attempts
    state["last_attempt"] = now.timestamp()
    return state


def record_result(state, now, ok, hit_daily_quota=False):
    if ok:
        state["last_success"] = now.timestamp()
        state["blocked_until"] = 0
        state["last_error"] = None
    elif hit_daily_quota:
        # no point trying again until the allowance resets
        state["blocked_until"] = quota_reset_local(now).timestamp()
        state["last_error"] = "Out of Gemini requests for today."
    return state
