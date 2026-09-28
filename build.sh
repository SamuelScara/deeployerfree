#!/usr/bin/env bash
# Builds the Linux executable into dist/DeepLoyerFree
set -euo pipefail
cd "$(dirname "$0")"
uv run --with pyside6 --with pyinstaller \
  pyinstaller --onefile --windowed --noconfirm --name DeepLoyerFree --icon deeployerfree.ico deeployerfree.py
echo "Done: $(pwd)/dist/DeepLoyerFree"