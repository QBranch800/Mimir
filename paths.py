import os
import sys

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _user_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "Mimir")


DATA_DIR = os.environ.get("MIMIR_DATA_DIR") or (
    _user_data_dir() if FROZEN else APP_DIR)

os.makedirs(DATA_DIR, exist_ok=True)


def data(name):
    return os.path.join(DATA_DIR, name)
