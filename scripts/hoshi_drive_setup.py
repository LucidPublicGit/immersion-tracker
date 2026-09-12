#!/usr/bin/env python3
"""
Set up Google Drive ``ttu-reader-data`` visibility for the Hoshi poller.

Uses the same service-account JSON as Sheets. Hoshi writes the folder under
*your* Google account; this script finds it once shared with the SA, or
creates an empty folder under the SA (not used by Hoshi) only with --create-sa-folder.

Typical flow:
  1. On Boox: Hoshi → Sync → connect Google → enable autosync
  2. Share My Drive / ttu-reader-data with the SA email (Viewer is enough)
  3. python scripts/hoshi_drive_setup.py --wait 300
  4. docker rebuild / POST /api/hoshi/sync
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SA_PATHS = [
    ROOT / "data" / "google-service-account.json",
    Path("/app/data/google-service-account.json"),
]
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_NAME = "ttu-reader-data"


def load_sa_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials

    path = next((p for p in SA_PATHS if p.is_file()), None)
    if not path:
        raise SystemExit("Missing data/google-service-account.json")
    info = json.loads(path.read_text(encoding="utf-8"))
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    creds.refresh(Request())
    return creds, info.get("client_email", "")


def drive_get(creds, path: str, params: dict | None = None) -> dict:
    import httpx

    r = httpx.get(
        f"https://www.googleapis.com/drive/v3/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {creds.token}"},
        params=params or {},
        timeout=60,
    )
    if r.status_code >= 400:
        raise SystemExit(f"Drive API {r.status_code}: {r.text[:400]}")
    return r.json()


def drive_post(creds, path: str, body: dict, params: dict | None = None) -> dict:
    import httpx

    r = httpx.post(
        f"https://www.googleapis.com/drive/v3/{path.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        params=params or {},
        json=body,
        timeout=60,
    )
    if r.status_code >= 400:
        raise SystemExit(f"Drive API {r.status_code}: {r.text[:400]}")
    return r.json()


def find_folders(creds, name: str) -> list[dict]:
    name_esc = name.replace("'", "\\'")
    q = (
        f"mimeType='{FOLDER_MIME}' and name='{name_esc}' and trashed=false"
    )
    data = drive_get(
        creds,
        "files",
        {
            "q": q,
            "fields": "files(id,name,owners,shared,webViewLink,parents)",
            "pageSize": "20",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "allDrives",
        },
    )
    return list(data.get("files") or [])


def create_folder(creds, name: str) -> dict:
    return drive_post(
        creds,
        "files",
        {
            "name": name,
            "mimeType": FOLDER_MIME,
        },
        params={"fields": "id,name,webViewLink"},
    )


def list_book_children(creds, folder_id: str) -> list[dict]:
    fid = folder_id.replace("'", "\\'")
    q = (
        f"'{fid}' in parents and mimeType='{FOLDER_MIME}' and trashed=false"
    )
    data = drive_get(
        creds,
        "files",
        {
            "q": q,
            "fields": "files(id,name)",
            "pageSize": "50",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    return list(data.get("files") or [])


def patch_settings_folder_id(folder_id: str) -> None:
    cfg = ROOT / "config" / "settings.yaml"
    if not cfg.is_file():
        print(f"No {cfg}; skip patch")
        return
    text = cfg.read_text(encoding="utf-8")
    new, n = re.subn(
        r"(?m)^(\s*root_folder_id:\s*)([\"']?)[^\"'\n]*\2\s*$",
        rf'\1"{folder_id}"',
        text,
        count=1,
    )
    if n == 0:
        # insert under hoshi if missing
        if "root_folder_id:" not in text:
            new = text.replace(
                "root_folder_name:",
                f'root_folder_id: "{folder_id}"\n  root_folder_name:',
                1,
            )
        else:
            print("Could not patch root_folder_id")
            return
    cfg.write_text(new, encoding="utf-8")
    print(f"Patched config/settings.yaml root_folder_id={folder_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Seconds to poll until folder is visible to the SA (0 = once)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Poll interval seconds when --wait > 0",
    )
    parser.add_argument(
        "--create-sa-folder",
        action="store_true",
        help="Create empty folder under the service account (Hoshi will NOT use this)",
    )
    parser.add_argument(
        "--no-patch",
        action="store_true",
        help="Do not write root_folder_id into settings.yaml",
    )
    args = parser.parse_args()

    creds, email = load_sa_creds()
    print(f"Service account: {email}")
    print(f"Looking for folder name: {args.name!r}")
    print()
    print("If the folder is missing, on the Boox:")
    print("  1. Hoshi → Settings → Sync → connect Google + enable autosync")
    print("  2. Read a page so stats upload")
    print("  3. In Google Drive (browser), share  ttu-reader-data  with:")
    print(f"       {email}")
    print("     as Viewer or Editor")
    print()

    deadline = time.time() + max(0, args.wait)
    folders: list[dict] = []
    while True:
        folders = find_folders(creds, args.name)
        if folders:
            break
        if args.wait <= 0 or time.time() >= deadline:
            break
        left = int(deadline - time.time())
        print(f"  not visible yet… retry in {args.interval}s ({left}s left)")
        time.sleep(max(1, args.interval))

    if not folders and args.create_sa_folder:
        print("Creating empty folder under the service account…")
        created = create_folder(creds, args.name)
        folders = [created]
        print(
            "NOTE: Hoshi writes under *your* My Drive, not the SA. "
            "Share *your* ttu-reader-data with the SA instead of using this empty folder."
        )

    if not folders:
        print("RESULT: folder not visible to the service account yet.")
        print("Share My Drive → ttu-reader-data with the email above, then re-run:")
        print(f"  python scripts/hoshi_drive_setup.py --wait 300")
        return 2

    print(f"Found {len(folders)} folder(s):")
    chosen = folders[0]
    for f in folders:
        owners = ", ".join(
            o.get("emailAddress") or o.get("displayName") or "?"
            for o in (f.get("owners") or [])
        )
        print(f"  id={f.get('id')}  owners=[{owners}]  link={f.get('webViewLink') or ''}")
        books = list_book_children(creds, f["id"])
        print(f"    book subfolders: {len(books)}")
        for b in books[:15]:
            print(f"      - {b.get('name')}")
        if len(books) > 15:
            print(f"      … +{len(books) - 15} more")

    folder_id = chosen["id"]
    if not args.no_patch:
        patch_settings_folder_id(folder_id)

    print()
    print("Next:")
    print("  .\\scripts\\docker\\rebuild.ps1")
    print("  Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/hoshi/sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
