"""A small local server for Mimir.

It serves the same index.html you can open from the file system, and adds the two
things a plain page cannot do: refresh the briefing, and save your API keys.

It binds to 127.0.0.1 on purpose. The refresh endpoint runs the pipeline and the
keys endpoint writes to .env, so this is not something to expose to a network.
"""

import os
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

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
}
run_lock = threading.Lock()


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
    scored = os.path.join(HERE, "scored.json")
    return jsonify({
        "server": True,
        "running": run_state["running"],
        "step": run_state["step"],
        "started": run_state["started"],
        "finished": run_state["finished"],
        "ok": run_state["ok"],
        "log": run_state["log"],
        # whether each key is set, never the value itself
        "keys": {name: bool(env.get(name)) for name in KEYS},
        "keyLabels": KEYS,
        "dataUpdated": os.path.getmtime(scored) if os.path.exists(scored) else None,
    })


@app.post("/api/refresh")
def refresh():
    with run_lock:
        if run_state["running"]:
            return jsonify({"error": "A refresh is already running."}), 409
        run_state.update({
            "running": True, "step": "Starting", "started": time.time(),
            "finished": None, "ok": None, "log": [],
        })
    threading.Thread(target=pipeline_worker, daemon=True).start()
    return jsonify({"started": True})


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
    print(f"Mimir is running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    except OSError as exc:
        print(f"\nCould not start on port {port}: {exc}")
        print(f"Something else is using it. Try: PORT=5112 {os.path.basename(PYTHON)} app.py")
        sys.exit(1)
