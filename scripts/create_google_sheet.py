#!/usr/bin/env python3
"""
Create a Google Spreadsheet with Immersion Tracker tabs + headers.

Requires a Google Cloud *service account* JSON key with Sheets + Drive APIs enabled.

Usage (host, with venv):
  set GOOGLE_APPLICATION_CREDENTIALS=data\\google-service-account.json
  python scripts/create_google_sheet.py

Or:
  python scripts/create_google_sheet.py --credentials data/google-service-account.json

Then share is automatic (owned by service account). Open the printed URL in your browser
(you must share the sheet with *your* Google account as Editor — see printed instructions).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TABS = {
    "Logs": [
        "id",
        "timestamp",
        "content_type",
        "title",
        "series_key",
        "source",
        "amount",
        "unit",
        "activity",
        "tadoku_mode",
        "tadoku_status",
        "tadoku_score_estimate",
        "watch_ratio",
        "notes",
    ],
    "Manual Entry": [
        "content_type",
        "title",
        "amount",
        "unit",
        "series_key",
        "activity",
        "notes",
        "imported",
    ],
    "Catalog": [
        "series_key",
        "display_title",
        "content_type",
        "aliases",
        "tadoku_override",
        "default_unit",
        "notes",
    ],
    "Tadoku Queue": [
        "id",
        "timestamp",
        "title",
        "content_type",
        "amount",
        "unit",
        "score",
        "tadoku_mode",
        "tadoku_status",
        "remote_id",
    ],
    "Metrics": ["metric", "value"],
    "Rules": [
        "content_type",
        "tadoku_mode",
        "notes",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Immersion Tracker Google Sheet")
    parser.add_argument(
        "--credentials",
        "-c",
        default="",
        help="Path to service account JSON (default: env or data/google-service-account.json)",
    )
    parser.add_argument(
        "--title",
        default="Immersion Tracker",
        help="Spreadsheet title",
    )
    parser.add_argument(
        "--share-with",
        default="",
        help="Your personal Gmail to grant Editor access (recommended)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    cred_path = args.credentials
    if not cred_path:
        import os

        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not cred_path:
        candidate = root / "data" / "google-service-account.json"
        if candidate.is_file():
            cred_path = str(candidate)

    if not cred_path or not Path(cred_path).is_file():
        print(
            "ERROR: Service account JSON not found.\n"
            "  1. Google Cloud Console → create service account\n"
            "  2. Enable Google Sheets API + Google Drive API\n"
            "  3. Download JSON key → save as data/google-service-account.json\n"
            "  4. Re-run this script\n",
            file=sys.stderr,
        )
        return 1

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Install deps: pip install gspread google-auth", file=sys.stderr)
        return 1

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    gc = gspread.authorize(creds)

    with open(cred_path, encoding="utf-8") as f:
        sa_email = json.load(f).get("client_email", "(unknown)")

    print(f"Using service account: {sa_email}")
    sh = gc.create(args.title)

    # First sheet rename + headers
    first = True
    for tab_name, headers in TABS.items():
        if first:
            ws = sh.sheet1
            ws.update_title(tab_name)
            first = False
        else:
            ws = sh.add_worksheet(title=tab_name, rows=1000, cols=max(20, len(headers)))
        ws.update("A1", [headers])
        # sample row for Manual Entry
        if tab_name == "Manual Entry":
            ws.update(
                "A2",
                [
                    [
                        "book",
                        "Example book title",
                        "10",
                        "pages",
                        "book:example",
                        "reading",
                        "delete me",
                        "",
                    ]
                ],
            )
        if tab_name == "Rules":
            ws.update(
                "A2",
                [
                    ["youtube", "pending", "server config is source of truth; this tab is reference"],
                    ["anime", "pending", ""],
                    ["book", "pending", ""],
                ],
            )

    share_email = args.share_with.strip()
    if share_email:
        sh.share(share_email, perm_type="user", role="writer")
        print(f"Shared as Editor with: {share_email}")
    else:
        print(
            "\nIMPORTANT: The spreadsheet is owned by the service account.\n"
            f"  In Google Drive you will not see it under your account until you share it.\n"
            f"  Open the URL below while logged in… actually use this from a script:\n"
            f"  Or re-run with:  --share-with you@gmail.com\n"
            f"  Service account email to share FROM Drive is not needed if we share now.\n"
        )

    spreadsheet_id = sh.id
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    print("\n=== Created ===")
    print(f"URL:  {url}")
    print(f"ID:   {spreadsheet_id}")
    print("\nPut this in config/settings.yaml:")
    print(
        f"""
sheets:
  enabled: true
  spreadsheet_id: "{spreadsheet_id}"
  service_account_file: "/app/data/google-service-account.json"
"""
    )
    print(
        "Ensure data/google-service-account.json is mounted (Docker uses ./data → /app/data).\n"
        "Then: .\\scripts\\docker\\rebuild.ps1   # or restart\n"
        "Then: .\\scripts\\docker\\sheets-sync.ps1\n"
    )

    # Write helper file for humans
    out = root / "data" / "google-sheet-info.txt"
    out.write_text(
        f"spreadsheet_id={spreadsheet_id}\nurl={url}\nservice_account={sa_email}\n",
        encoding="utf-8",
    )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
