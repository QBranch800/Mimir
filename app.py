"""A small local server for Mimir.

It serves the same index.html you can open from the file system, and adds the two
things a plain page cannot do: refresh the briefing, and save your API keys.

It binds to 127.0.0.1 on purpose. The refresh endpoint runs the pipeline and the
keys endpoint writes to .env, so this is not something to expose to a network.
"""

import datetime
import os
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import scheduler

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
PYTHON = sys.executable

# env var -> label shown in the UI
KEYS = {
    "ALPHA_VANTAGE_API_KEY": "Alpha Vantage",
    "GEMINI_API_KEY": "Gemini",
    "NEWSAPI_KEY": "NewsAPI",
}

app = Flask(__name__, static_folder=None)

run_state = {
    "running": False,
    "step": None,
    "started": None,
    "finished": None,
    "ok": None,
    "log": [],
    "trigger": None,          # "you" or "schedule"
}
run_lock = threading.Lock()
schedule_note = "Starting up."


def read_env():
    values = {}
    if not os.path.exists(ENV_PATH):
        return values
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(updates):
    """Update or add keys in .env, leaving every other line as it was."""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name in remaining:
                out.append(f"{name}={remaining.pop(name)}")
                continue
        out.append(line)

    for name, value in remaining.items():
        out.append(f"{name}={value}")

    with open(ENV_PATH, "w") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.chmod(ENV_PATH, 0o600)


def pipeline_worker():
    steps = [
        ("fetch_news.py", "Alpha Vantage headlines"),
        ("fetch_gdelt.py", "GDELT geopolitics"),
        ("fetch_newsapi.py", "NewsAPI geopolitics"),
        ("filter_news.py", "Filtering and deduping"),
        ("score_news.py", "Scoring with Gemini"),
    ]
    ok = True
    try:
        for script, label in steps:
            run_state["step"] = label
            result = subprocess.run(
                [PYTHON, os.path.join(HERE, script)],
                cwd=HERE, capture_output=True, text=True, timeout=1800,
            )
            tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
            run_state["log"].append({
                "step": label,
                "ok": result.returncode == 0,
                "detail": tail[0][:200],
            })
            if result.returncode != 0:
                # a news source failing is survivable; filtering and scoring are not
                if script in ("filter_news.py", "score_news.py"):
                    ok = False
                    break
    except Exception as exc:                       # noqa: BLE001 - surfaced to the page
        run_state["log"].append({"step": "run", "ok": False, "detail": str(exc)[:200]})
        ok = False
    finally:
        run_state["ok"] = ok
        run_state["running"] = False
        run_state["step"] = None
        run_state["finished"] = time.time()
        _remember_outcome(ok)


def _remember_outcome(ok):
    """Record how a run went, so the scheduler knows whether to try again."""
    hit_quota = any(
        "out of gemini requests" in (entry.get("detail") or "").lower()
        for entry in run_state["log"]
    )
    cfg, state = scheduler.load_schedule()
    scheduler.record_result(state, datetime.datetime.now().astimezone(), ok, hit_quota)
    scheduler.save_schedule(cfg, state)


def start_pipeline(trigger):
    """Begin a run unless one is already going. Returns True if it started."""
    with run_lock:
        if run_state["running"]:
            return False
        run_state.update({
            "running": True, "step": "Starting", "started": time.time(),
            "finished": None, "ok": None, "log": [], "trigger": trigger,
        })
    threading.Thread(target=pipeline_worker, daemon=True).start()
    return True


def scheduler_loop():
    """Check once a minute whether a refresh is due. This is the whole scheduler:
    no cron, no launchd, no Task Scheduler, so it behaves the same on every OS and
    in a hosted deployment."""
    global schedule_note
    first_pass = True
    while True:
        try:
            cfg, state = scheduler.load_schedule()
            now = datetime.datetime.now().astimezone()

            if run_state["running"]:
                schedule_note = "A refresh is running."
            else:
                due, reason = scheduler.should_run(cfg, state, now)
                stale = first_pass and not due and scheduler.is_stale(
                    _data_mtime(), cfg, now)

                if due or stale:
                    why = "schedule" if due else "startup"
                    schedule_note = ("Refreshing now." if due else
                                     "The briefing was out of date, so refreshing now.")
                    scheduler.record_attempt(state, now)
                    scheduler.save_schedule(cfg, state)
                    start_pipeline(why)
                else:
                    schedule_note = reason
            first_pass = False
        except Exception as exc:                   # noqa: BLE001 - never kill the thread
            schedule_note = f"Scheduler problem: {exc}"
        time.sleep(60)


def _data_mtime():
    scored = os.path.join(HERE, "scored.json")
    return os.path.getmtime(scored) if os.path.exists(scored) else None


@app.after_request
def no_store(response):
    # the briefing changes under the page's feet, so never let a stale copy stick
    if request.path.endswith((".json", ".js")) or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.get("/<path:filename>")
def static_file(filename):
    # send_from_directory refuses to escape HERE, so a crafted path cannot read
    # files elsewhere on the machine
    if filename == ".env" or filename.startswith(".env"):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(HERE, filename)


@app.get("/api/status")
def status():
    env = read_env()
    cfg, state = scheduler.load_schedule()
    return jsonify({
        "server": True,
        "running": run_state["running"],
        "step": run_state["step"],
        "started": run_state["started"],
        "finished": run_state["finished"],
        "ok": run_state["ok"],
        "log": run_state["log"],
        "trigger": run_state["trigger"],
        # whether each key is set, never the value itself
        "keys": {name: bool(env.get(name)) for name in KEYS},
        "keyLabels": KEYS,
        "dataUpdated": _data_mtime(),
        "schedule": {
            "enabled": cfg["enabled"],
            "time": cfg["time"],
            "note": schedule_note,
            "lastSuccess": state.get("last_success"),
            "quotaResetsAt": scheduler.default_time(),
        },
    })


@app.post("/api/refresh")
def refresh():
    if not start_pipeline("you"):
        return jsonify({"error": "A refresh is already running."}), 409
    return jsonify({"started": True})


@app.post("/api/schedule")
def set_schedule():
    payload = request.get_json(silent=True) or {}
    cfg, state = scheduler.load_schedule()

    if "enabled" in payload:
        cfg["enabled"] = bool(payload["enabled"])
    if payload.get("time"):
        value = str(payload["time"])
        try:
            hour, minute = value.split(":")
            if not (0 <= int(hour) < 24 and 0 <= int(minute) < 60):
                raise ValueError
            cfg["time"] = f"{int(hour):02d}:{int(minute):02d}"
        except (ValueError, TypeError):
            return jsonify({"error": "Time should look like 07:30."}), 400
        # a new slot deserves a fresh chance today
        state["attempts"] = {}
        state["last_attempt"] = 0

    scheduler.save_schedule(cfg, state)
    return jsonify({"enabled": cfg["enabled"], "time": cfg["time"]})


@app.post("/api/keys")
def save_keys():
    payload = request.get_json(silent=True) or {}
    updates = {}
    for name in KEYS:
        if name not in payload:
            continue
        value = str(payload[name]).strip()
        if not value:                       # blank means "leave the stored one alone"
            continue
        if "\n" in value or "\r" in value:
            return jsonify({"error": f"{KEYS[name]} key contains a line break."}), 400
        updates[name] = value

    if not updates:
        return jsonify({"saved": []})

    write_env(updates)
    return jsonify({"saved": [KEYS[name] for name in updates]})


if __name__ == "__main__":
    # not 5000: macOS gives that to the AirPlay receiver, which answers with a 403
    port = int(os.environ.get("PORT", "5111"))
    cfg, _ = scheduler.load_schedule()
    print(f"Mimir is running at http://127.0.0.1:{port}")
    if cfg["enabled"]:
        print(f"It will refresh itself daily at {cfg['time']}, and on startup if the "
              f"briefing is more than {cfg['stale_hours']} hours old.")
    else:
        print("Automatic refresh is off. Turn it on in Settings.")
    print("Press Ctrl+C to stop.")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    except OSError as exc:
        print(f"\nCould not start on port {port}: {exc}")
        print(f"Something else is using it. Try: PORT=5112 {os.path.basename(PYTHON)} app.py")
        sys.exit(1)
