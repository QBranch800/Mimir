"""A small local server for Mimir.

It serves the same index.html you can open from the file system, and adds the two
things a plain page cannot do: refresh the briefing, and save your API keys.

It binds to 127.0.0.1 on purpose. The refresh endpoint runs the pipeline and the
keys endpoint writes to .env, so this is not something to expose to a network.
"""

import datetime
import json
import os
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import paths
import freshness

HERE = paths.APP_DIR
ENV_PATH = paths.data(".env")
PYTHON = sys.executable


def step_command(script):
    """How to run one pipeline step.

    From a checkout that is just python on the script. Inside a packaged app there is
    no python to call and no .py on disk, so the bundled executable re-runs itself with
    --step and imports that module instead.
    """
    if paths.FROZEN:
        return [sys.executable, "--step", script[:-3]]
    return [PYTHON, os.path.join(HERE, script)]

# env var -> label shown in the UI
KEYS = {
    "GEMINI_API_KEY": "Gemini",
}

app = Flask(__name__, static_folder=None)

run_state = {
    "running": False,
    "step": None,
    "started": None,
    "finished": None,
    "ok": None,
    "log": [],
    "trigger": None,          # "you" or "open"
    "hit_quota": False,       # every Gemini model was out of requests
}
run_lock = threading.Lock()
refresh_note = "Starting up."


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


FULL_RUN = [
    ("fetch_rss.py", "Monetary policy feeds"),
    ("fetch_google.py", "Google News headlines"),
    ("fetch_gdelt.py", "GDELT geopolitics"),
    ("filter_news.py", "Filtering and deduping"),
    ("score_news.py", "Scoring with Gemini"),
]
# finishing a run cut short today: scoring picks up only what is missing, and fetching
# again would spend the news sources' allowances for nothing
FINISH_RUN = [("score_news.py", "Scoring with Gemini")]


def pipeline_worker(steps=FULL_RUN):
    ok = True
    try:
        for script, label in steps:
            run_state["step"] = label
            result = subprocess.run(
                step_command(script),
                cwd=paths.DATA_DIR, capture_output=True, text=True, timeout=1800,
            )
            # keep the whole thing, so a failed run can be looked at afterwards
            with open(paths.data("run.log"), "a") as log:
                log.write(f"\n===== {label} ({time.strftime('%Y-%m-%d %H:%M:%S')}) "
                          f"rc={result.returncode}\n")
                log.write(result.stdout or "")
                if result.stderr:
                    log.write("--- stderr ---\n" + result.stderr)

            if "every model is out of requests" in (result.stdout or "").lower():
                run_state["hit_quota"] = True

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
    """Record how a run went, so opening the app knows whether trying again is pointless."""
    global refresh_note
    now = datetime.datetime.now().astimezone()
    enabled, state = freshness.load()
    freshness.record_result(state, now, ok, run_state["hit_quota"])
    freshness.save(enabled, state)
    # so the page says how things ended up rather than still saying "refreshing"
    left = _unfinished()
    action, refresh_note = freshness.needs_refresh(True, state, _data_mtime(), now, left)
    if action == "finish":
        refresh_note = (f"{left} articles could not be scored this time. Opening Mimir again "
                        f"will try them.")


def start_pipeline(trigger, steps=FULL_RUN):
    """Begin a run unless one is already going. Returns True if it started."""
    with run_lock:
        if run_state["running"]:
            return False
        run_state.update({
            "running": True, "step": "Starting", "started": time.time(),
            "finished": None, "ok": None, "log": [], "trigger": trigger,
            "hit_quota": False,
        })
    threading.Thread(target=pipeline_worker, args=(steps,), daemon=True).start()
    return True


def refresh_on_open():
    """Called once when the app starts: refresh if the briefing is not from today.

    There is deliberately no timer. One inside the app can only fire while the app is
    running, so it rarely did; opening the app is the moment the briefing is wanted.
    """
    global refresh_note
    try:
        enabled, state = freshness.load()
        action, refresh_note = freshness.needs_refresh(
            enabled, state, _data_mtime(), datetime.datetime.now().astimezone(), _unfinished())
        if action == "full":
            start_pipeline("open")
        elif action == "finish":
            start_pipeline("open", FINISH_RUN)
    except Exception as exc:                       # noqa: BLE001 - shown on the page
        refresh_note = f"Could not check the briefing: {exc}"


def _unfinished():
    """How many of the latest fetched articles still have no score."""
    try:
        with open(paths.data("filtered.json")) as f:
            fetched = {a["url"] for a in json.load(f)}
        with open(paths.data("scored.json")) as f:
            scored = {a["url"] for a in json.load(f)}
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    return len(fetched - scored)


def _data_mtime():
    scored = paths.data("scored.json")
    return os.path.getmtime(scored) if os.path.exists(scored) else None


def is_listening(port, host="127.0.0.1"):
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def pick_port(preferred=None):
    """The configured port, or the next free one. Not 5000: macOS answers that with
    its AirPlay receiver."""
    import socket
    start = preferred or int(os.environ.get("PORT", "5111"))
    for candidate in range(start, start + 20):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    return start


@app.after_request
def no_store(response):
    # the briefing changes under the page's feet, so never let a stale copy stick
    if request.path.endswith((".json", ".js")) or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(paths.APP_DIR, "index.html")


DATA_FILES = {"scored.json", "briefing_data.js", "filtered.json"}


@app.get("/<path:filename>")
def static_file(filename):
    # send_from_directory refuses to escape the folder it is given, so a crafted path
    # cannot read files elsewhere on the machine
    if filename.startswith(".env"):
        return jsonify({"error": "not found"}), 404
    folder = paths.DATA_DIR if filename in DATA_FILES else HERE
    return send_from_directory(folder, filename)


@app.get("/api/status")
def status():
    env = read_env()
    enabled, state = freshness.load()
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
        "refreshOnOpen": {
            "enabled": enabled,
            "note": refresh_note,
            "lastSuccess": state.get("last_success"),
        },
    })


@app.post("/api/refresh")
def refresh():
    if not start_pipeline("you"):
        return jsonify({"error": "A refresh is already running."}), 409
    return jsonify({"started": True})


@app.post("/api/refresh-on-open")
def set_refresh_on_open():
    payload = request.get_json(silent=True) or {}
    enabled, state = freshness.load()
    if "enabled" in payload:
        enabled = bool(payload["enabled"])
    freshness.save(enabled, state)
    return jsonify({"enabled": enabled})


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
    port = pick_port()
    print(f"Mimir is running at http://127.0.0.1:{port}")
    print("It refreshes now if the briefing is not from today. Press Ctrl+C to stop.")
    threading.Thread(target=refresh_on_open, daemon=True).start()
    try:
        # load_dotenv=False: Flask otherwise searches the working directory for a .env
        # and loads it into the environment, which would quietly override the keys the
        # person saved in their data directory
        app.run(host="127.0.0.1", port=port, debug=False, load_dotenv=False)
    except OSError as exc:
        print(f"\nCould not start on port {port}: {exc}")
        print(f"Something else is using it. Try: PORT=5112 {os.path.basename(PYTHON)} app.py")
        sys.exit(1)
