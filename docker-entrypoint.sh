#!/bin/sh
set -e
mkdir -p /app/data /app/data/tadoku_export
if [ ! -f /app/config/settings.yaml ]; then
  cp /app/config/settings.example.yaml /app/config/settings.yaml
fi
exec "$@"
