#!/usr/bin/env bash
# Runs DeepLoyerFree from source. Uses uv if available, otherwise a local virtualenv.
set -euo pipefail
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  exec uv run deeployerfree.py "$@"
fi

PYTHON="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON" ]; then
  echo "Python 3.10+ is required (or install uv: https://docs.astral.sh/uv/)." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating .venv and installing dependencies..."
  "$PYTHON" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip -q
  .venv/bin/python -m pip install -r requirements.txt -q
fi
exec .venv/bin/python deeployerfree.py "$@"
