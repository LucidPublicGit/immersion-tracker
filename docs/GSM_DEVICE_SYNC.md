# Shared GSM history

Run GSM locally on each device. The tracker can host a personal GSM encrypted-v2
relay and keep a paired, combined history for character counting. A sentence ID
counts once even when present on multiple devices. New offline activity is counted
when it arrives; replaying an upload does not reset its counting position.

The supported wire format is described in
[GSM's encrypted-sync documentation](https://github.com/bpwhelan/GameSentenceMiner/blob/main/docs/ENCRYPTED_SYNC.md).
Text history, edits, deletions, timestamps and Anki note IDs sync. The native GSM
client rebuilds derived statistics. Media files, game-library metadata and capture
settings are outside GSM's encrypted-v2 protocol. Anki cards/media can use Anki's
own sync. This does not synchronize game saves or OBS scenes.

The trusted tracker host holds the pairing key as a paired device. Configure
`GSM_SYNC_TOKEN` and `GSM_SYNC_KEY` in its private environment. Use HTTPS. Never
put the token, key, history database or pairing JSON in Git.

Before enabling the hub, seed `/app/data/gsm-shared/gsm.db` with a consistent SQLite
backup of the existing GSM snapshot. Keep its history/cursor and the tracker's
local cursor unchanged. Point `gsm.db_path` at that shared file. The relay uses
`/app/data/gsm-sync/relay.db`; both directories belong in normal state backups.
Existing legacy snapshot uploads may remain for rollback, but must not replace
the shared file. The encrypted relay retains events/transfers for 30 days with a
256 MiB quota. Expired encrypted content is pruned on the next relay request.
Local GSM databases and the shared history remain durable.

On each device, install a GSM version supporting **Settings → Advanced → Encrypted
device sync**. Enter the common tracker HTTPS URL, access token and pairing key;
enable sync and run Sync now. Settings sync is optional and off by default.

Alternatively, create a private pairing JSON containing `url`, `token`, `key`, then
run `scripts/gsm/pair_device.py --pairing <private-file> --gsm-data <active-folder>`
with GSM's own Python environment. The helper backs up the local database and
configuration, configures 60-second automatic sync, and performs the first sync.
It keeps all existing local history. Windows normally uses
`%APPDATA%/GameSentenceMiner`; use the active data folder reported by GSM on Macs
and on installations with custom locations. Run the helper while GSM is closed,
or let it use the running backend's localhost API. Each device remains usable
offline. Start GSM to resume automatic exchange.

For a new device or one offline beyond retention, use **Prepare device transfer**
on a current device before syncing. Keep the pairing key in private backups.
Sync deletions propagate to paired devices; backups provide recovery.

Use **Inbox → Match GSM games** (`/gsm-games`) to resolve different titles or
local game IDs. Choose the canonical game, preview affected lines, then save the
match. Suggestions require an explicit save. Existing and future shared tracker
history use that association; the PCs retain their original capture names and
local IDs. This does not synchronize the full local game libraries.

Remove a saved match to restore the original associations. Repairs preserve
sentence IDs, text, play timestamps and skipped/exported history. Finish or skip
an unfinished GSM export first. A changed history or skip position requires a
fresh preview. Missing canonical games can be added with an optional VNDB ID.
