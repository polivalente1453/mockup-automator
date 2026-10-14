#!/bin/sh
# Mac/Linux: start the Mockup Automator. Extra arguments are passed through (e.g. ./start.sh install).
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3.11 || command -v python3 || command -v python)
[ -n "$PY" ] || { echo "Python 3.9+ is required: https://www.python.org/downloads/"; exit 1; }
exec "$PY" launcher.py "$@"
