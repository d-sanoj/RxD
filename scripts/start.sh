#!/usr/bin/env bash
# One script to set up and run RxD on macOS or Linux.
#
#   ./scripts/start.sh                 set up if needed, seed the demo data, run the server on :8000
#   ./scripts/start.sh --setup-only    set up and seed, then exit
#   ./scripts/start.sh --models        also pull the two Ollama models (needs Ollama installed)
#   ./scripts/start.sh --test          run the test suite before starting
#   ./scripts/start.sh --port 9000     use another port
#   ./scripts/start.sh --reset         delete storage/ (database, vectors, uploads) before seeding
#   ./scripts/start.sh --no-reload     run without auto-reload
#
# Options can be combined, e.g.  ./scripts/start.sh --models --test --port 9000

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT=8000
PY="${PYTHON:-python3}"
SETUP_ONLY=0
PULL_MODELS=0
RUN_TESTS=0
RESET=0
RELOAD="--reload"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup-only) SETUP_ONLY=1 ;;
    --models) PULL_MODELS=1 ;;
    --test) RUN_TESTS=1 ;;
    --reset) RESET=1 ;;
    --no-reload) RELOAD="" ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# 1. Python 3.11+
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python not found. Install Python 3.11+ (https://www.python.org/downloads/) or set PYTHON=/path/to/python3.12."
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required; found $("$PY" --version 2>&1)."
  exit 1
fi

# 2. Virtual environment and dependencies (re-installed only when requirements change)
say "Python environment"
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv
fi
STAMP=".venv/.requirements.sha"
CURRENT="$(cat requirements.txt requirements-dev.txt | shasum -a 256 | cut -d' ' -f1)"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$CURRENT" ]]; then
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt -r requirements-dev.txt
  echo "$CURRENT" > "$STAMP"
  echo "Dependencies installed."
else
  echo "Dependencies already up to date."
fi

# 3. .env with a real JWT secret
say "Configuration"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi
if grep -q '^RXD_JWT_SECRET=change-me' .env; then
  SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  # portable in-place edit (BSD and GNU sed)
  .venv/bin/python - "$SECRET" <<'PY'
import pathlib, sys
p = pathlib.Path(".env")
lines = [f"RXD_JWT_SECRET={sys.argv[1]}" if l.startswith("RXD_JWT_SECRET=change-me") else l
         for l in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
PY
  echo "Generated a random RXD_JWT_SECRET in .env."
fi

# 4. Optional: Ollama models
if [[ $PULL_MODELS -eq 1 ]]; then
  say "Ollama models"
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama is not installed. Get it from https://ollama.com/download, then re-run with --models."
    exit 1
  fi
  ollama pull qwen2.5:1.5b
  ollama pull nomic-embed-text
fi

# 5. Optional: tests
if [[ $RUN_TESTS -eq 1 ]]; then
  say "Tests"
  .venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q
fi

# 6. Database, demo data and vectors
if [[ $RESET -eq 1 ]]; then
  say "Resetting storage/"
  rm -rf storage
fi
say "Seeding demo data (safe to repeat)"
.venv/bin/python scripts/seed.py 2>/dev/null | grep -v '^{' || true

if [[ $SETUP_ONLY -eq 1 ]]; then
  say "Setup complete. Start with: ./scripts/start.sh"
  exit 0
fi

# 7. Run
say "Starting RxD on http://localhost:${PORT}  (API docs: /docs · sign in: dr.evans / demo-clinician)"
echo "Stop with Ctrl+C."
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" $RELOAD
