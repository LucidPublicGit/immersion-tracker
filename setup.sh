#!/usr/bin/env bash
# Immersion Tracker — one-command setup (Linux / macOS)
#   git clone … && cd immersion-tracker && ./setup.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/scripts/docker/setup.sh" "$@"
