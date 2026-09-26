#!/bin/bash
# Loads .env and starts the web app. Used by launchd (KeepAlive) so it's
# always running at http://127.0.0.1:8420 without you having to start it.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec python3 -m src.webapp
