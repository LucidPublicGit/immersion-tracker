#!/usr/bin/env python3
"""
Log in with YOUR Google account and save a token for Sheets sync.

Use this when your organization blocks service account keys
(iam.disableServiceAccountKeyCreation).

Prerequisites:
  1. Google Cloud project with Sheets API + Drive API enabled
  2. OAuth consent screen configured (External or Internal)
  3. OAuth client ID type: "Desktop app"
  4. Download client JSON → data/google-oauth-client.json

Run ON YOUR PC (not inside Docker the first time — needs a browser):

  cd C:\\DevEnv\\immersion-tracker
  .\\.venv\\Scripts\\activate
  pip install -r requirements.txt
  python scripts/google_oauth_login.py

Then enable sheets in config/settings.yaml and restart Docker.
The token file data/google-oauth-token.json is mounted into the container.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="OAuth login for Immersion Tracker Sheets")
    parser.add_argument(
        "--client",
        default=str(root / "data" / "google-oauth-client.json"),
        help="OAuth Desktop client secrets JSON from Google Cloud Console",
    )
    parser.add_argument(
        "--token",
        default=str(root / "data" / "google-oauth-token.json"),
        help="Where to write the user refresh token",
    )
    args = parser.parse_args()

    client_path = Path(args.client)
    token_path = Path(args.token)

    if not client_path.is_file():
        print(
            f"""
ERROR: OAuth client secrets not found:
  {client_path}

Create them (this is NOT a service account key — org key policy usually does not block this):

  1. https://console.cloud.google.com/apis/credentials
  2. Configure OAuth consent screen if prompted
       - User type: External (personal) or Internal (Workspace-only)
       - App name: Immersion Tracker
       - Your email as developer/support
       - Scopes: add spreadsheets + drive (or continue and scopes come from this script)
       - Test users: add YOUR Gmail if app is in Testing
  3. Create Credentials → OAuth client ID → Application type: Desktop app
  4. Download JSON → save as:
       {client_path}

  5. Enable APIs: Google Sheets API + Google Drive API

Then re-run this script.
""",
            file=sys.stderr,
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("pip install google-auth-oauthlib", file=sys.stderr)
        return 1

    print("Opening browser for Google sign-in…")
    print("Sign in with the same Google account that owns/can edit your spreadsheet.")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    # local server flow; works on Windows with a normal browser
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nSaved token → {token_path}")
    print(
        """
Next:
  1. config/settings.yaml:
       sheets:
         enabled: true
         spreadsheet_id: "YOUR_SPREADSHEET_ID"
         oauth_token_file: "/app/data/google-oauth-token.json"
         oauth_client_secrets_file: "/app/data/google-oauth-client.json"

  2. You do NOT need to share the sheet with a service account email
     (you signed in as yourself).

  3. Restart Docker:
       .\\scripts\\docker\\rebuild.ps1
       .\\scripts\\docker\\sheets-sync.ps1
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
