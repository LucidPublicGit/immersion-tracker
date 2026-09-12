"""
Point Tautulli's Webhook agent at Immersion Tracker with a proper JSON body + secret.

Run inside the tautulli container or against the mounted config DB:
  python scripts/fix_tautulli_webhook.py /config/tautulli.db changeme
"""
from __future__ import annotations

import json
import sqlite3
import sys

WATCHED_BODY = json.dumps(
    {
        "action": "watched",
        "rating_key": "{rating_key}",
        "title": "{title}",
        "grandparent_title": "{show_name}",
        "full_title": "{full_title}",
        "library_name": "{library_name}",
        "media_type": "{media_type}",
        "duration": "{duration}",
        "progress_percent": "{progress_percent}",
        "season_num": "{season_num}",
        "episode_num": "{episode_num}",
        "year": "{year}",
        "watched": True,
    },
    separators=(",", ":"),
)


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/tautulli/tautulli.db"
    secret = sys.argv[2] if len(sys.argv) > 2 else "changeme"
    hook = (
        f"http://immersion-tracker:8000/api/webhooks/tautulli?secret={secret}"
    )
    config = {
        "hook": hook,
        "method": "POST",
        # Tautulli may ignore unknown keys; body is per-trigger columns
    }

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, notifier_config, on_watched, on_watched_body FROM notifiers "
        "WHERE agent_name='webhook'"
    ).fetchall()
    if not rows:
        print("No webhook notifiers found")
        sys.exit(1)
    for nid, cfg, on_watched, body in rows:
        cur.execute(
            """
            UPDATE notifiers
            SET notifier_config = ?,
                on_watched = 1,
                on_watched_body = ?
            WHERE id = ?
            """,
            (json.dumps(config), WATCHED_BODY, nid),
        )
        print(f"Updated notifier_id={nid}")
        print(f"  hook={hook}")
        print(f"  on_watched=1")
        print(f"  body={WATCHED_BODY[:120]}...")
    con.commit()
    con.close()
    print("Done. Use Test Notification in Tautulli, or finish an episode.")


if __name__ == "__main__":
    main()
