#!/usr/bin/env bash
# Deprecated name — use setup-wizard.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/setup-wizard.sh" "$@"
