#!/usr/bin/env python3
"""Cross-platform launcher (Mac, Windows, Linux). Standard library only, so it runs before setup.

  mockup                  start the web UI and open the browser (sets up on first run)
  mockup install          add the `mockup` command so it works from any folder
  mockup setup            (re)install dependencies
  mockup render 334 335   any other arguments go to the CLI (see `mockup --help`)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WIN = os.name == "nt"
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if WIN else "bin/python")
PORT = int(os.environ.get("PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}"
os.environ.setdefault("PYTHONUNBUFFERED", "1")  # show server logs live in any terminal
CHECK_IMPORTS = "import flask, PIL, numpy, yaml, googleapiclient, google_auth_oauthlib"


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], cwd=str(ROOT), **kw)


def env_ok() -> bool:
    return VPY.exists() and run([VPY, "-c", CHECK_IMPORTS], capture_output=True).returncode == 0


def setup(force: bool = False) -> None:
    if not force and env_ok():
        return
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is required. Install it from https://www.python.org/downloads/")
    print("Setting up Mockup Automator (first run takes a minute)...")
    if not VPY.exists():
        run([sys.executable, "-m", "venv", VENV], check=True)
    run([VPY, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    run([VPY, "-m", "pip", "install", "-q", "-r", ROOT / "requirements.txt"], check=True)
    for d in ("templates", "designs", "output"):
        (ROOT / d).mkdir(exist_ok=True)
    has_templates = any((ROOT / "templates").glob("*/*.png"))
    if not has_templates and not (ROOT / "config" / "credentials.json").exists():
        print("No Google Drive credentials yet: creating demo data so you can try it.")
        run([VPY, "-m", "app.cli", "samples"], check=True)
    print("Setup complete.")


def is_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/config", timeout=1.5):
            return True
    except Exception:
        return False


def serve() -> None:
    setup()
    if is_running():
        print(f"Mockup Automator is already running at {URL}")
        webbrowser.open(URL)
        return
    print(f"Starting Mockup Automator at {URL}  (press Ctrl+C to stop)")
    proc = subprocess.Popen([str(VPY), "-m", "app.cli", "serve", "--port", str(PORT)], cwd=str(ROOT))
    try:
        for _ in range(60):
            if proc.poll() is not None:
                sys.exit(proc.returncode)
            if is_running():
                webbrowser.open(URL)
                break
            time.sleep(0.5)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        print("Stopped.")


def install() -> None:
    """Put a `mockup` command on the PATH that points at this folder."""
    setup()
    launcher = ROOT / "launcher.py"
    if WIN:
        # WindowsApps is on every user's PATH by default, so no PATH editing is needed.
        bin_dir = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WindowsApps"
        target = bin_dir / "mockup.cmd"
        target.write_text(f'@echo off\r\n"{VPY}" "{launcher}" %*\r\n')
    else:
        bin_dir = Path.home() / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / "mockup"
        target.write_text(f'#!/bin/sh\nexec "{VPY}" "{launcher}" "$@"\n')
        target.chmod(0o755)
        on_path = str(bin_dir) in os.environ.get("PATH", "").split(os.pathsep)
        if not on_path:
            line = 'export PATH="$HOME/.local/bin:$PATH"  # added by Mockup Automator\n'
            for rc in (".zshrc", ".bashrc", ".bash_profile"):
                f = Path.home() / rc
                if rc == ".zshrc" or f.exists():
                    text = f.read_text() if f.exists() else ""
                    if ".local/bin" not in text:
                        f.write_text(text + ("\n" if text and not text.endswith("\n") else "") + line)
            print("Added ~/.local/bin to your PATH. Open a new terminal window to use `mockup`.")
    print(f"Installed: {target}")
    print("You can now type `mockup` in any terminal to start the tool.")
    print("If you move this project folder, run `install` again from its new location.")


def main(argv) -> None:
    if not argv:
        return serve()
    cmd = argv[0]
    if cmd == "install":
        return install()
    if cmd == "setup":
        return setup(force=True)
    setup()
    sys.exit(run([VPY, "-m", "app.cli", *argv]).returncode)


if __name__ == "__main__":
    main(sys.argv[1:])
