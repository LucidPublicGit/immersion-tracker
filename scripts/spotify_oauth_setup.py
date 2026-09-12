#!/usr/bin/env python3
"""
Authorize Spotify once and save a refresh token for podcast poll.

Scopes:
  user-read-recently-played
  user-read-playback-state
  user-read-currently-playing

Prerequisites:
  1. Spotify Developer Dashboard app: https://developer.spotify.com/dashboard
  2. Add Redirect URI: http://127.0.0.1:8766/callback
  3. Client ID + Client Secret (or env SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET)

Run ON YOUR PC (needs a browser):

  cd path/to/immersion-tracker
  .\\.venv\\Scripts\\activate
  pip install -r requirements.txt
  python scripts/spotify_oauth_setup.py

Token is written to data/spotify-oauth-token.json (mounted into Docker as
/app/data/spotify-oauth-token.json). Then enable spotify in config/settings.yaml
and rebuild Docker.
"""
from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCOPES = [
    "user-read-recently-played",
    "user-read-playback-state",
    "user-read-currently-playing",
]
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_REDIRECT = "http://127.0.0.1:8766/callback"
DEFAULT_PORT = 8766


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def exchange_code(
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> dict:
    import httpx

    r = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30.0,
    )
    if r.status_code >= 400:
        raise SystemExit(f"Token exchange failed HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    if not body.get("access_token") or not body.get("refresh_token"):
        raise SystemExit(f"Token response incomplete: {body}")
    return body


def run_local_callback(port: int, expected_state: str, timeout: float = 300.0) -> str:
    """Start a one-shot HTTP server; return authorization code."""
    result: dict[str, str] = {}
    error_box: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/callback", "/"):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("error"):
                error_box["error"] = qs["error"][0]
                msg = f"Authorization denied: {error_box['error']}"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    f"<html><body><h1>Spotify auth failed</h1><p>{msg}</p></body></html>".encode()
                )
                return
            code = (qs.get("code") or [""])[0]
            state = (qs.get("state") or [""])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return
            if state != expected_state:
                error_box["error"] = "state_mismatch"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch")
                return
            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Spotify authorized</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )

        def log_message(self, format, *args):  # noqa: A003
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1.0
    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if result.get("code") or error_box.get("error"):
            break
    server.server_close()
    if error_box.get("error"):
        raise SystemExit(f"OAuth error: {error_box['error']}")
    if not result.get("code"):
        raise SystemExit("Timed out waiting for Spotify redirect (no code received)")
    return result["code"]


def main() -> int:
    parser = argparse.ArgumentParser(description="OAuth login for Immersion Tracker Spotify")
    parser.add_argument(
        "--client-id",
        default=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        help="Spotify app client id (or SPOTIFY_CLIENT_ID)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        help="Spotify app client secret (or SPOTIFY_CLIENT_SECRET)",
    )
    parser.add_argument(
        "--token",
        default=str(ROOT / "data" / "spotify-oauth-token.json"),
        help="Where to write the token JSON",
    )
    parser.add_argument(
        "--redirect",
        default=DEFAULT_REDIRECT,
        help=f"Redirect URI registered in Spotify dashboard (default {DEFAULT_REDIRECT})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local callback port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print auth URL only; do not open a browser",
    )
    parser.add_argument(
        "--manual-code",
        default="",
        help="Skip local server: paste authorization code from redirect URL",
    )
    args = parser.parse_args()

    client_id = (args.client_id or "").strip()
    client_secret = (args.client_secret or "").strip()

    # Fall back to settings.yaml if present
    if not client_id or not client_secret:
        try:
            import yaml

            settings_path = ROOT / "config" / "settings.yaml"
            if settings_path.is_file():
                y = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
                sp = y.get("spotify") or {}
                client_id = client_id or str(sp.get("client_id") or "").strip()
                client_secret = client_secret or str(sp.get("client_secret") or "").strip()
        except Exception:  # noqa: BLE001
            pass

    if not client_id or not client_secret:
        print(
            """
ERROR: Spotify client_id and client_secret are required.

  1. https://developer.spotify.com/dashboard → Create app
  2. Settings → Redirect URIs → add:
       http://127.0.0.1:8766/callback
  3. Copy Client ID + Client Secret

Then either:
  set SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
  or pass --client-id / --client-secret
  or set them under spotify: in config/settings.yaml
""",
            file=sys.stderr,
        )
        return 1

    redirect_uri = (args.redirect or DEFAULT_REDIRECT).strip()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "show_dialog": "true",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("Spotify OAuth for Immersion Tracker")
    print(f"  redirect: {redirect_uri}")
    print(f"  scopes:   {' '.join(SCOPES)}")
    print()
    print("Open this URL if the browser does not open:\n")
    print(auth_url)
    print()

    if args.manual_code:
        code = args.manual_code.strip()
    else:
        if not args.no_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:  # noqa: BLE001
                print("(could not open browser automatically)", file=sys.stderr)
        print(f"Waiting for callback on port {args.port}…")
        # If redirect host/port differ, user should use --manual-code
        code = run_local_callback(args.port, state)

    body = exchange_code(
        code=code,
        redirect_uri=redirect_uri,
        client_id=client_id,
        client_secret=client_secret,
    )

    token_path = Path(args.token)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    expires_in = int(body.get("expires_in") or 3600)
    payload = {
        "refresh_token": body["refresh_token"],
        "access_token": body["access_token"],
        "expires_at": int(time.time()) + expires_in,
        "token_type": body.get("token_type") or "Bearer",
        "scope": body.get("scope") or " ".join(SCOPES),
    }
    token_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"\nSaved token → {token_path}")
    print(
        """
Next:
  1. config/settings.yaml:
       spotify:
         enabled: true
         client_id: "YOUR_CLIENT_ID"       # or env SPOTIFY_CLIENT_ID
         client_secret: "YOUR_SECRET"      # or env SPOTIFY_CLIENT_SECRET
         token_file: "/app/data/spotify-oauth-token.json"
         podcasts_only: true
         show_allowlist: []               # optional show ids / name substrings
         tadoku_default: pending

  2. Ensure data/spotify-oauth-token.json is mounted into the container
     (default docker-compose maps ./data → /app/data).

  3. Rebuild / restart Docker:
       .\\scripts\\docker\\rebuild.ps1

  4. Confirm poll (after listening to a podcast episode):
       # logs with source=spotify appear in /queue or /api/logs?source=spotify
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
