import sys
import threading
import time


def run_step(name):
    import os
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream, None) is None:
            setattr(sys, stream, open(os.devnull, "w"))

    allowed = {"fetch_rss", "fetch_google", "fetch_gdelt", "filter_news", "score_news"}
    if name not in allowed:
        print(f"Unknown step: {name}")
        return 1
    __import__(name)
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--step":
        return run_step(sys.argv[2])

    import webview

    import app as server
    import paths
    port = server.pick_port()

    threading.Thread(
        target=lambda: server.app.run(host="127.0.0.1", port=port, debug=False,
                                      use_reloader=False, load_dotenv=False),
        daemon=True,
    ).start()
    threading.Thread(target=server.refresh_on_open, daemon=True).start()

    for _ in range(50):
        if server.is_listening(port):
            break
        time.sleep(0.1)

    print(f"Mimir: data in {paths.DATA_DIR}")

    webview.create_window("Mimir", f"http://127.0.0.1:{port}",
                          width=1280, height=860, min_size=(820, 600))
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
