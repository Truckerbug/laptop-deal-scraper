#!/bin/bash
# Wrapper so launchd (which doesn't read .env files) can still get the
# eBay credentials. Loads .env if present, then runs the scraper.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec python3 -m src.main
