#!/usr/bin/env bash
# First-time Docker setup for Immersion Tracker (Linux / macOS)
# Run from repo root:  ./setup.sh
# Or:                  ./scripts/docker/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

NO_BROWSER=0
WITH_PLEX=0
for arg in "$@"; do
  case "$arg" in
    --no-browser) NO_BROWSER=1 ;;
    --with-plex) WITH_PLEX=1 ;;
    -h|--help)
      echo "Usage: $0 [--no-browser] [--with-plex]"
      exit 0
      ;;
  esac
done

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '\n' | tr '+/=' 'xxx'
  else
    head -c 24 /dev/urandom | base64 | tr -d '\n' | tr '+/=' 'xxx'
  fi
}

get_env() {
  local key="$1"
  [[ -f .env ]] || { echo ""; return; }
  # shellcheck disable=SC2002
  grep -E "^[[:space:]]*${key}=" .env | tail -n1 | cut -d= -f2- | sed 's/^["'\'']//;s/["'\'']$//' || true
}

set_env() {
  local key="$1" val="$2"
  if [[ -f .env ]] && grep -qE "^[[:space:]]*${key}=" .env; then
    # portable-ish in-place replace
    local tmp
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$val" '
      BEGIN{done=0}
      $0 ~ "^[[:space:]]*"k"=" { print k"="v; done=1; next }
      { print }
      END{ if(!done) print k"="v }
    ' .env >"$tmp" && mv "$tmp" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

echo "== Immersion Tracker — setup =="

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running (or not installed)." >&2
  echo "Install Docker, start it, then re-run." >&2
  echo "  https://docs.docker.com/get-docker/" >&2
  exit 1
fi

mkdir -p data/tadoku_export data/gsm data/mpv config

if [[ ! -f config/settings.yaml ]]; then
  if [[ ! -f config/settings.example.yaml ]]; then
    echo "Missing config/settings.example.yaml" >&2
    exit 1
  fi
  cp config/settings.example.yaml config/settings.yaml
  echo "Created config/settings.yaml"
else
  echo "config/settings.yaml already exists"
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
  else
    echo "WEBHOOK_SECRET=changeme" > .env
  fi
  echo "Created .env"
fi

secret="$(get_env WEBHOOK_SECRET)"
generated=0
if [[ -z "${secret// }" || "$secret" == "changeme" ]]; then
  secret="$(gen_secret)"
  set_env WEBHOOK_SECRET "$secret"
  generated=1
  echo "Generated WEBHOOK_SECRET (saved in .env)"
fi

cat > data/extension-connect.txt <<EOF
Immersion Tracker — browser extension settings
==============================================
Server URL:      http://127.0.0.1:8000
Webhook secret:  $secret

Firefox: about:debugging#/runtime/this-firefox → Load Temporary Add-on
         → select extension/manifest.json
Chrome:  chrome://extensions → Developer mode → Load unpacked → extension/

Then open the extension popup → gear → paste URL + secret → Test server.
EOF

echo
echo "Building and starting immersion-tracker..."
if [[ "$WITH_PLEX" -eq 1 ]]; then
  docker compose --profile plex up --build -d
else
  docker compose up --build -d immersion-tracker
fi

echo
echo "Waiting for health..."
ok=0
for _ in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    ok=1
    break
  fi
  sleep 1
done

echo
if [[ "$ok" -eq 1 ]]; then
  echo "Ready."
else
  echo "Container started but health not ready yet."
  echo "  docker compose logs -f immersion-tracker"
fi

echo
echo "Open:"
echo "  UI:     http://127.0.0.1:8000/"
echo "  Queue:  http://127.0.0.1:8000/queue"
echo "  Health: http://127.0.0.1:8000/api/health"
echo "  Docs:   http://127.0.0.1:8000/docs"
echo
echo "Webhook secret (extension / Tautulli):"
echo "  $secret"
if [[ "$generated" -eq 1 ]]; then
  echo "  (also in .env and data/extension-connect.txt)"
else
  echo "  (from existing .env; see data/extension-connect.txt)"
fi
echo
echo "Next (optional):"
echo "  YouTube: load extension/ in Firefox/Chrome — details in data/extension-connect.txt"
echo "  Sheets:  see SETUP.md (Phase 2) — skip if you only want local DB"
echo "  Plex:    ./setup.sh --with-plex"
echo "  Full:    SETUP.md"
echo
echo "Daily:"
echo "  docker compose up -d immersion-tracker"
echo "  docker compose down"
echo "  docker compose logs -f immersion-tracker"

if [[ "$ok" -eq 1 && "$NO_BROWSER" -eq 0 ]]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:8000/queue" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:8000/queue" >/dev/null 2>&1 || true
  fi
fi
