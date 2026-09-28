import datetime
import json
import os
import zoneinfo

import paths

STATE_PATH = paths.data("refresh.json")

QUOTA_TZ = "America/Los_Angeles"


def quota_reset_local(now=None):
    now = now or datetime.datetime.now().astimezone()
    now_pacific = now.astimezone(zoneinfo.ZoneInfo(QUOTA_TZ))
    midnight = (now_pacific + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(now.tzinfo)


def load():
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
    os.replace(tmp, STATE_PATH)


def needs_refresh(enabled, state, data_mtime, now, unfinished=0):
    if not enabled:
        return None, "Refreshing on open is off. Use Refresh now when you want one."

    blocked_until = state.get("blocked_until") or 0
    if now.timestamp() < blocked_until:
        when = datetime.datetime.fromtimestamp(blocked_until, now.tzinfo)
        return None, (f"Gemini is out of requests until {when:%H:%M}, so the briefing was "
                      f"not refreshed. Open Mimir again after that, or press Refresh now.")

    if not data_mtime:
        return "full", "Building your first briefing."

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
        state["blocked_until"] = quota_reset_local(now).timestamp()
    return state
