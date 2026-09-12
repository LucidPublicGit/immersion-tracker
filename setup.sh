#!/usr/bin/env bash
# Immersion Tracker — one-command setup (Linux / macOS)
#   ./setup.sh
#   Feature wizard (optional): ./scripts/setup-wizard.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/scripts/docker/setup.sh" "$@"
