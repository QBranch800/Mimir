"""Build Mimir into a double-clickable desktop app.

Run this on the OS you want to build for: PyInstaller does not cross compile, so a
Mac produces Mimir.app, Windows produces Mimir.exe and Linux produces a binary. The
result lands in dist/.

    python3 build_desktop.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = ";" if os.name == "nt" else ":"        # PyInstaller's --add-data separator

# Imported by name at runtime, so PyInstaller cannot see them by following imports.
PIPELINE_STEPS = ["fetch_news", "fetch_newsapi", "filter_news", "score_news"]

# Shipped alongside the code and only ever read.
ASSETS = ["index.html", ("assets", "assets")]


def main():
    try:
        import PyInstaller                    # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: pip install pyinstaller pywebview")
        return 1

    for stale in ("build", "dist"):
        shutil.rmtree(os.path.join(HERE, stale), ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Mimir",
        "--windowed",                          # a real app window, no terminal
        "--noconfirm",
        "--clean",
        os.path.join(HERE, "desktop.py"),
    ]

    # each platform insists on its own icon format, so use one only if it is there
    icon_name = {"darwin": "logo.icns", "win32": "logo.ico"}.get(sys.platform)
    if icon_name:
        icon = os.path.join(HERE, "assets", icon_name)
        if os.path.exists(icon):
            cmd[-1:-1] = ["--icon", icon]
        else:
            print(f"No assets/{icon_name}, so the app gets a default icon.\n")

    for item in ASSETS:
        src, dest = item if isinstance(item, tuple) else (item, ".")
        cmd[-1:-1] = ["--add-data", f"{os.path.join(HERE, src)}{SEP}{dest}"]

    for module in PIPELINE_STEPS:
        cmd[-1:-1] = ["--hidden-import", module]

    # these are reached dynamically inside their libraries
    for module in ("google.genai", "trafilatura", "dotenv", "flask", "webview"):
        cmd[-1:-1] = ["--hidden-import", module]

    print("Building. This takes a few minutes.\n")
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        return result.returncode

    built = os.path.join(HERE, "dist")
    print(f"\nDone. Look in {built}")
    print("Your keys and briefing are kept outside the app, in the folder each OS uses "
          "for application data, so an update never wipes them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
