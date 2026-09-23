"""Where Mimir's code lives, and where its data lives.

Run from a checkout these are the same folder, which is what you want while working
on it. Installed as a desktop app they must not be: the application bundle is read
only, so keys, fetched news and settings belong in the place each OS keeps user data.

Everything that reads or writes a file goes through here, so the scripts behave the
same either way.
"""

import os
import sys

FROZEN = getattr(sys, "frozen", False)

# Where index.html, assets and the scripts themselves live.
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


# MIMIR_DATA_DIR lets you point a packaged app at a different folder, which is also
# how the tests keep out of the way of real data.
DATA_DIR = os.environ.get("MIMIR_DATA_DIR") or (
    _user_data_dir() if FROZEN else APP_DIR)

os.makedirs(DATA_DIR, exist_ok=True)


def data(name):
    """A file Mimir reads and writes: keys, fetched news, scores, settings."""
    return os.path.join(DATA_DIR, name)


def asset(name):
    """A file that ships with Mimir and is only ever read."""
    return os.path.join(APP_DIR, name)
