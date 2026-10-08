#!/usr/bin/env bash
# APPLY setup for macOS and Linux. From the folder you cloned into:  bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ask() { read -r -p "$1 [Y/n] " reply; [[ ! "$reply" =~ ^[nN] ]]; }

if ! command -v uv >/dev/null; then
  if ask "Install uv (the Python manager APPLY uses)?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else echo "uv is required."; exit 1; fi
fi
if ! command -v pdflatex >/dev/null; then
  echo "No TeX yet — letters can be written but not typeset. $(uv run python -c 'from apply.generate import tex_hint; print(tex_hint())' 2>/dev/null || true)"
fi

uv sync
uv run apply setup
