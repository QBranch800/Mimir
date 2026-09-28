import importlib.util
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = ";" if os.name == "nt" else ":"

PIPELINE_STEPS = ["fetch_rss", "fetch_google", "fetch_gdelt", "filter_news", "score_news"]

ASSETS = ["index.html", ("assets", "assets")]


def main():
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed. Run: pip install pyinstaller pywebview")
        return 1

    for stale in ("build", "dist"):
        shutil.rmtree(os.path.join(HERE, stale), ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Mimir",
        "--windowed",
        "--noconfirm",
        "--clean",
        os.path.join(HERE, "desktop.py"),
    ]

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

    for module in ("google.genai", "trafilatura", "dotenv", "flask", "webview"):
        cmd[-1:-1] = ["--hidden-import", module]

    print("Building. This takes a few minutes.\n")
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        return result.returncode

    built = os.path.join(HERE, "dist")
    if sys.platform == "darwin":
        sign_adhoc(os.path.join(built, "Mimir.app"))

    print(f"\nDone. Look in {built}")
    print("Your keys and briefing are kept outside the app, in the folder each OS uses "
          "for application data, so an update never wipes them.")
    return 0


def sign_adhoc(app_path):
    if not os.path.exists(app_path):
        return
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", app_path],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("Signed with an ad-hoc signature.")
    else:
        print(f"Could not sign: {result.stderr.strip()[:120]}")


if __name__ == "__main__":
    sys.exit(main())
