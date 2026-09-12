#!/usr/bin/env bash
# Feature wizard — no assumed installs. Mirrors setup-wizard.ps1.
#
#   ./scripts/setup-wizard.sh
#   ./scripts/setup-wizard.sh --tadoku --plex --gsm
#   ./scripts/setup-wizard.sh --all --yes --no-pause
#   ./scripts/setup-wizard.sh --registration-id UUID --gsm-data-dir /path --timezone America/Los_Angeles
#   ./scripts/setup-wizard.sh --plex-libraries 'Anime=anime,TV Shows=show'
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_CORE=0; NO_BROWSER=0; NO_PAUSE=0; YES=0; FLAG_MODE=0
WANT_TADOKU=0; WANT_PLEX=0; WANT_GSM=0; WANT_HOSHI=0; WANT_YT=0; WANT_SHEETS=0
REG_ID=""; CONTEST_ID=""; CONTEST_NAME=""; GSM_DIR=""; TIMEZONE=""; PLEX_LIBS=""
NEED_RESTART=0; CONFIG_ONLY=0; TRACKER_UP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-core) SKIP_CORE=1 ;;
    --no-browser) NO_BROWSER=1 ;;
    --no-pause) NO_PAUSE=1 ;;
    --yes|-y) YES=1 ;;
    --tadoku) WANT_TADOKU=1; FLAG_MODE=1 ;;
    --plex) WANT_PLEX=1; FLAG_MODE=1 ;;
    --gsm) WANT_GSM=1; FLAG_MODE=1 ;;
    --hoshi) WANT_HOSHI=1; FLAG_MODE=1 ;;
    --youtube) WANT_YT=1; FLAG_MODE=1 ;;
    --sheets) WANT_SHEETS=1; FLAG_MODE=1 ;;
    --all) WANT_TADOKU=1; WANT_PLEX=1; WANT_GSM=1; WANT_HOSHI=1; WANT_YT=1; WANT_SHEETS=1; FLAG_MODE=1 ;;
    --registration-id) REG_ID="${2:-}"; shift ;;
    --contest-id) CONTEST_ID="${2:-}"; shift ;;
    --contest-name) CONTEST_NAME="${2:-}"; shift ;;
    --gsm-data-dir) GSM_DIR="${2:-}"; shift ;;
    --timezone) TIMEZONE="${2:-}"; shift ;;
    --plex-libraries) PLEX_LIBS="${2:-}"; shift ;;
    -h|--help)
      sed -n '1,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

banner() { printf '\n============================================================\n  %s\n============================================================\n' "$*"; }
step() { printf '\n>> %s\n' "$*"; }
ok() { printf '   OK  %s\n' "$*"; }
warn() { printf '   !!  %s\n' "$*" >&2; }
info() { printf '   %s\n' "$*"; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

ask_yes() {
  local q="$1" def="${2:-Y}"
  if [[ "$YES" -eq 1 ]]; then [[ "$def" == "Y" ]]; return $?; fi
  local hint="Y/n"; [[ "$def" == "N" ]] && hint="y/N"
  local a=""
  if [[ -t 0 ]]; then read -r -p "   $q [$hint] " a || true; fi
  a="${a:-$def}"
  [[ "$a" =~ ^[Yy]([Ee][Ss])?$ ]]
}

read_val() {
  local prompt="$1" def="${2:-}"
  if [[ -n "$def" && ( "$YES" -eq 1 || "$FLAG_MODE" -eq 1 ) ]]; then echo "$def"; return; fi
  local a=""
  if [[ -t 0 ]]; then
    if [[ -n "$def" ]]; then read -r -p "   $prompt [$def] " a || true
    else read -r -p "   $prompt " a || true
    fi
  fi
  echo "${a:-$def}"
}

pause() {
  [[ "$NO_PAUSE" -eq 1 || "$YES" -eq 1 || "$FLAG_MODE" -eq 1 ]] && return 0
  if [[ -t 0 ]]; then read -r -p "   ${1:-Press Enter to continue} " _ || true; fi
}

open_url() {
  [[ "$NO_BROWSER" -eq 1 ]] && { info "Open: $1"; return; }
  if have_cmd xdg-open; then xdg-open "$1" >/dev/null 2>&1 || info "Open: $1"
  elif have_cmd open; then open "$1" >/dev/null 2>&1 || info "Open: $1"
  else info "Open: $1"; fi
}

docker_state() {
  have_cmd docker || { echo missing; return; }
  if docker compose version >/dev/null 2>&1 || { have_cmd docker-compose && docker-compose version >/dev/null 2>&1; }; then
    :
  else
    echo no_compose; return
  fi
  if docker info >/dev/null 2>&1; then echo ok; else echo not_running; fi
}

show_docker_help() {
  case "$1" in
    missing) warn "Docker not installed."; info "https://docs.docker.com/get-docker/"; open_url "https://docs.docker.com/get-docker/" ;;
    no_compose) warn "Compose missing."; info "https://docs.docker.com/compose/install/" ;;
    not_running) warn "Docker engine not running — start it." ;;
  esac
}

show_when_docker_works() {
  echo
  printf '   When Docker is installed and running:\n'
  info "1. ./setup.sh"
  info "2. ./scripts/setup-wizard.sh   (same --tadoku/--plex/… flags)"
  info "3. Open http://127.0.0.1:8000/queue"
}

compose() {
  [[ "$DOCKER_STATE" == ok ]] || { warn "Skipping docker compose ($DOCKER_STATE)"; return 1; }
  docker compose "$@"
}

tracker_up() {
  have_cmd curl || return 1
  curl -fsS --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'
}

get_env() {
  local key="$1"
  [[ -f .env ]] || { echo ""; return; }
  grep -E "^[[:space:]]*${key}=" .env | tail -n1 | cut -d= -f2- | sed 's/^["'\'']//;s/["'\'']$//' || true
}

set_env() {
  local key="$1" val="$2"
  touch .env
  if grep -qE "^[[:space:]]*${key}=" .env; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$val" 'BEGIN{d=0} $0 ~ "^[[:space:]]*"k"=" {print k"="v; d=1; next} {print} END{if(!d) print k"="v}' .env >"$tmp" && mv "$tmp" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

gen_secret() {
  if have_cmd openssl; then openssl rand -base64 24 | tr -d '\n' | tr '+/=' 'xxx'
  elif [[ -r /dev/urandom ]]; then head -c 24 /dev/urandom | base64 2>/dev/null | tr -d '\n' | tr '+/=' 'xxx'
  else echo "changeme-please-edit"; fi
}

ensure_files() {
  mkdir -p data/tadoku_export config
  [[ -f config/settings.yaml || ! -f config/settings.example.yaml ]] || { cp config/settings.example.yaml config/settings.yaml; ok "Created config/settings.yaml"; }
  if [[ ! -f .env ]]; then
    [[ -f .env.example ]] && cp .env.example .env || echo "WEBHOOK_SECRET=changeme" > .env
    ok "Created .env"
  fi
  local secret; secret="$(get_env WEBHOOK_SECRET)"
  if [[ -z "${secret// }" || "$secret" == "changeme" ]]; then
    secret="$(gen_secret)"; set_env WEBHOOK_SECRET "$secret"; ok "Generated WEBHOOK_SECRET"
  fi
  local tz; tz="$(get_env TZ)"
  if [[ -n "$TIMEZONE" ]]; then
    set_env TZ "$TIMEZONE"; ok "TZ=$TIMEZONE"; NEED_RESTART=1
  elif [[ -z "${tz// }" || "$tz" == "UTC" ]]; then
    if [[ "$YES" -eq 0 && "$FLAG_MODE" -eq 0 ]]; then
      info "Container TZ defaults often UTC — set for correct log times."
      local ans; ans="$(read_val "IANA timezone (e.g. America/Los_Angeles; Enter skip)" "${TZ:-}")"
      if [[ -n "$ans" ]]; then set_env TZ "$ans"; ok "TZ=$ans"; NEED_RESTART=1; fi
    fi
  fi
  secret="$(get_env WEBHOOK_SECRET)"
  cat > data/extension-connect.txt <<EOF
Server URL (this PC):  http://127.0.0.1:8000
Server URL (LAN):      http://<this-host-lan-ip>:8000
Webhook secret:        ${secret}

Firewall: allow inbound TCP 8000 if other devices cannot reach the tracker.
EOF
}

set_registration_id() {
  local r="$1"
  [[ -f config/settings.yaml ]] || return 1
  local tmp; tmp="$(mktemp)"
  awk -v r="$r" '
    !done && $0 ~ /^[[:space:]]*registration_id:/ {
      match($0, /^[[:space:]]*/); ind=substr($0,RSTART,RLENGTH)
      print ind "registration_id: \"" r "\""; done=1; next
    } { print }
  ' config/settings.yaml >"$tmp" && mv "$tmp" config/settings.yaml
}

set_plex_library_map() {
  local spec="$1"
  [[ -f config/settings.yaml && -n "$spec" ]] || return 1
  python3 - "$spec" <<'PY' 2>/dev/null || return 1
import sys
from pathlib import Path
spec = sys.argv[1]
pairs = []
for part in spec.split(","):
    part = part.strip()
    if not part or "=" not in part: continue
    n, t = part.split("=", 1)
    n, t = n.strip(), t.strip()
    if n and t: pairs.append((n, t))
if not pairs: raise SystemExit(1)
p = Path("config/settings.yaml")
lines = p.read_text(encoding="utf-8").splitlines()
out = []
i = 0
replaced = False
while i < len(lines):
    line = lines[i]
    out.append(line)
    if line.strip() == "library_map:" and i > 0:
        # check we're under plex roughly: previous non-empty had plex or indent
        ind = line[: len(line) - len(line.lstrip())] + "  "
        i += 1
        while i < len(lines) and lines[i].startswith(ind[:4]) and lines[i].strip() and not lines[i].lstrip().startswith("#"):
            # skip old map lines with deeper indent
            if lines[i].startswith(ind) or (len(lines[i]) - len(lines[i].lstrip()) > len(ind) - 2):
                if lines[i].startswith(ind) or lines[i].startswith(ind.replace("  ", "    ")[: len(ind)]):
                    i += 1
                    continue
            break
        for n, t in pairs:
            out.append(f"{ind}{n}: {t}")
        replaced = True
        continue
    i += 1
if not replaced:
    # simpler: find library_map under file
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith("library_map:") or line.strip() == "library_map:":
            out.append(line)
            ind = "    "
            if line.startswith(" "):
                ind = line[: len(line) - len(line.lstrip())] + "  "
            i += 1
            while i < len(lines) and lines[i].startswith(ind):
                i += 1
            for n, t in pairs:
                out.append(f"{ind}{n}: {t}")
            replaced = True
            continue
        out.append(line)
        i += 1
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print(len(pairs))
PY
}

set_hoshi_enabled() {
  [[ -f config/settings.yaml ]] || return 1
  python3 <<'PY' 2>/dev/null || return 1
from pathlib import Path
p=Path("config/settings.yaml")
lines=p.read_text(encoding="utf-8").splitlines()
out=[]; in_h=False
for line in lines:
    if line.strip()=="hoshi:":
        in_h=True; out.append(line); continue
    if in_h and line and line[0].isalpha():
        in_h=False
    if in_h and line.lstrip().startswith("enabled:"):
        ind=line[:len(line)-len(line.lstrip())]
        out.append(f"{ind}enabled: true"); continue
    if in_h and line.lstrip().startswith("source:"):
        ind=line[:len(line)-len(line.lstrip())]
        out.append(f"{ind}source: drive"); continue
    out.append(line)
p.write_text("\n".join(out)+"\n", encoding="utf-8")
print("ok")
PY
}

banner "Immersion Tracker — setup wizard"
info "No assumed installs. Flags: --tadoku --plex --gsm --hoshi --youtube --sheets --all --yes"

banner "Prerequisites check"
DOCKER_STATE="$(docker_state)"
tracker_up && TRACKER_UP=1 || TRACKER_UP=0
info "Docker:  $DOCKER_STATE"
info "Tracker: $([[ $TRACKER_UP -eq 1 ]] && echo OK || echo 'not on :8000')"

if [[ "$DOCKER_STATE" != ok ]]; then
  show_docker_help "$DOCKER_STATE"
  if ! ask_yes "Continue with config / instructions only?" Y; then
    show_when_docker_works; exit 0
  fi
  CONFIG_ONLY=1
fi

ensure_files

if [[ "$TRACKER_UP" -eq 0 && "$CONFIG_ONLY" -eq 0 && "$SKIP_CORE" -eq 0 ]]; then
  if ask_yes "Start the tracker now (./setup.sh)?" "$([[ $FLAG_MODE -eq 1 ]] && echo N || echo Y)"; then
    if [[ -f ./setup.sh ]]; then bash ./setup.sh --no-browser || true
    elif [[ -f scripts/docker/setup.sh ]]; then bash scripts/docker/setup.sh --no-browser || true
    fi
    DOCKER_STATE="$(docker_state)"
    tracker_up && TRACKER_UP=1 || TRACKER_UP=0
  else
    CONFIG_ONLY=1
  fi
fi

if [[ "$FLAG_MODE" -eq 0 ]]; then
  banner "What do you want to set up?"
  ask_yes "Tadoku.app login + contest?" Y && WANT_TADOKU=1
  ask_yes "Plex / Tautulli?" N && WANT_PLEX=1
  ask_yes "GameSentenceMiner?" N && WANT_GSM=1
  ask_yes "Hoshi / Boox?" N && WANT_HOSHI=1
  ask_yes "YouTube extension?" N && WANT_YT=1
  ask_yes "Google Sheets?" N && WANT_SHEETS=1
fi

secret="$(get_env WEBHOOK_SECRET)"; [[ -n "$secret" ]] || secret=changeme

if [[ "$WANT_TADOKU" -eq 1 ]]; then
  banner "Tadoku.app"
  info "Needs tadoku.app account only."
  [[ "$FLAG_MODE" -eq 0 ]] && open_url "https://tadoku.app" && pause "When you have a contest, press Enter"
  if [[ "$TRACKER_UP" -eq 1 ]]; then
    [[ "$FLAG_MODE" -eq 0 ]] && open_url "http://127.0.0.1:8000/queue" && pause "After Save login, press Enter"
    if [[ -z "$REG_ID" ]] && ask_yes "List registrations now?" "$([[ $FLAG_MODE -eq 1 ]] && echo N || echo Y)"; then
      if [[ "$DOCKER_STATE" == ok ]] && docker inspect -f '{{.State.Running}}' immersion-tracker 2>/dev/null | grep -q true; then
        docker compose exec -T immersion-tracker python /app/scripts/tadoku_list_registrations.py || warn "list failed"
      elif have_cmd python3; then
        python3 scripts/tadoku_list_registrations.py || warn "list failed"
      else
        warn "Need running container or python3+httpx"
      fi
    fi
  else
    warn "Tracker not running — Save login after ./setup.sh"
  fi
  [[ -n "$REG_ID" ]] || REG_ID="$(read_val "Paste registration_id (Enter skip)")"
  if [[ -n "$REG_ID" ]]; then
    set_registration_id "$REG_ID" && ok "registration_id saved" || warn "edit settings.yaml manually"
    NEED_RESTART=1
  fi
fi

if [[ "$WANT_PLEX" -eq 1 ]]; then
  banner "Plex / Tautulli"
  info "Does not install Plex."
  if [[ "$CONFIG_ONLY" -eq 0 && "$DOCKER_STATE" == ok ]]; then
    if ask_yes "Start bundled Tautulli?" Y; then
      compose --profile plex up -d || true
      ok "http://127.0.0.1:8181"
      open_url "http://127.0.0.1:8181"
    fi
  else
    warn "Docker not ready — https://tautulli.com or finish Docker later"
  fi
  url="http://immersion-tracker:8000/api/webhooks/tautulli?secret=${secret}"
  hosturl="http://127.0.0.1:8000/api/webhooks/tautulli?secret=${secret}"
  cat > data/plex-tautulli-connect.txt <<EOF
Bundled Tautulli: http://127.0.0.1:8181
Start: docker compose --profile plex up -d
Webhook (Docker Tautulli): $url
Webhook (host): $hosturl
Method POST, Watched — JSON body in docs/PLEX.md
library_map keys = exact Plex library names
EOF
  ok "Wrote data/plex-tautulli-connect.txt"
  info "$url"
  pause "After webhook configured (or skip), press Enter"
  [[ -n "$PLEX_LIBS" ]] || PLEX_LIBS="$(read_val "Plex maps Name=type,... (Enter keep defaults)")"
  if [[ -n "$PLEX_LIBS" ]]; then
    if n="$(set_plex_library_map "$PLEX_LIBS")"; then ok "library_map updated ($n)"; NEED_RESTART=1
    else warn "Could not patch library_map — edit config/settings.yaml (needs python3)"; fi
  fi
fi

if [[ "$WANT_GSM" -eq 1 ]]; then
  banner "GameSentenceMiner"
  info "Separate install — https://github.com/GameSentenceMiner/GameSentenceMiner"
  found="$GSM_DIR"
  if [[ -z "$found" || ! -f "${found}/gsm.db" ]]; then
    found=""
    for dir in "${HOME}/.local/share/GameSentenceMiner" "${HOME}/GameSentenceMiner" "${HOME}/AppData/Roaming/GameSentenceMiner"; do
      [[ -f "${dir}/gsm.db" ]] && { found="$dir"; break; }
    done
    [[ -n "$found" ]] || found="$(read_val "Folder containing gsm.db (Enter skip)")"
  fi
  if [[ -n "$found" && -f "${found}/gsm.db" ]]; then
    set_env GSM_DATA_DIR "$found"; ok "GSM_DATA_DIR=$found"; NEED_RESTART=1
  else
    warn "gsm.db not found — install GSM then --gsm-data-dir"
  fi
fi

if [[ "$WANT_HOSHI" -eq 1 ]]; then
  banner "Hoshi / Boox"
  info "Blocked without Google Drive (stock Hoshi):"
  info "  [ ] Hoshi installed  [ ] Google connected  [ ] autosync/statistics"
  info "  [ ] ttu-reader-data in Drive  [ ] PC can read folder (OAuth or SA share)"
  pause "When checklist done (or skip), press Enter"
  if ask_yes "Enable hoshi poller (source=drive)?" Y; then
    set_hoshi_enabled && ok "hoshi.enabled=true" || info "Edit config/settings.yaml hoshi.enabled / source"
    NEED_RESTART=1
  fi
  info "docs/HOSHI.md"
fi

if [[ "$WANT_YT" -eq 1 ]]; then
  banner "YouTube extension"
  info "Browser only. Firewall: allow TCP 8000 for LAN clients."
  [[ -f extension/manifest.json ]] || warn "extension/manifest.json missing"
  cat > data/extension-connect.txt <<EOF
Server URL:      http://127.0.0.1:8000
LAN URL:         http://<host-lan-ip>:8000
Webhook secret:  ${secret}
Firefox temporary add-on / Chrome load unpacked → extension/
EOF
  ok "Wrote data/extension-connect.txt"
  [[ "$TRACKER_UP" -eq 1 ]] || warn "Tracker down — Test server fails until ./setup.sh"
fi

if [[ "$WANT_SHEETS" -eq 1 ]]; then
  banner "Google Sheets"
  info "Optional. docs/GOOGLE_SHEETS.md — SA or OAuth; wizard does not create GCP project."
fi

if [[ "$NEED_RESTART" -eq 1 ]]; then
  banner "Apply changes"
  if [[ "$CONFIG_ONLY" -eq 1 || "$DOCKER_STATE" != ok ]]; then
    warn "Config on disk; app not restarted."
    show_when_docker_works
  else
    compose up -d --force-recreate immersion-tracker || warn "restart failed"
    tracker_up && TRACKER_UP=1 || TRACKER_UP=0
  fi
fi

banner "Done"
if [[ "$TRACKER_UP" -eq 1 ]]; then
  info "Queue: http://127.0.0.1:8000/queue"
  open_url "http://127.0.0.1:8000/queue"
else
  warn "Tracker still not running."
  show_when_docker_works
fi
info "SETUP.md"
