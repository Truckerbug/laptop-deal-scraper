#!/bin/bash
# Loads .env and starts the web app. Used by launchd (KeepAlive) so it's
# always running at http://127.0.0.1:8420 without you having to start it.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Use the venv's python directly instead of `source venv/bin/activate` —
# launchd runs this without a login shell, so activation can silently no-op
# and fall through to whatever system python3 is first on launchd's (bare)
# PATH. That's exactly the "No module named 'flask'" you're seeing.
exec ./venv/bin/python -m src.webapp