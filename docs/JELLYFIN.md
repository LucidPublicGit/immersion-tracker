# Jellyfin → Immersion Tracker

Auto-log finished watches (default **≥ 90%** or marked played) into SQLite + Google Sheets.

Tautulli’s job for Plex is **notify on watched**. For Jellyfin that is the
[Webhook plugin](https://github.com/jellyfin/jellyfin-plugin-webhook) (Dashboard → Plugins → Catalog).

```
Jellyfin plays media → Webhook plugin (PlaybackStop) → POST /api/webhooks/jellyfin
                                                     → Immersion Tracker
```

**Where to look:** http://127.0.0.1:8000/queue or `/api/logs?source=jellyfin`

### Connecting a separate Jellyfin host

- Configure a Generic Webhook destination that posts Playback Stop events for
  episodes and movies to your tracker host. Use an address reachable from the
  Jellyfin container; localhost refers to that container, not the tracker.
- Supply the tracker host's `WEBHOOK_SECRET` using `X-Webhook-Secret` and keep
  it out of screenshots and logs.
- Set `JELLYFIN_URL` and a dedicated `JELLYFIN_API_KEY` in the tracker's ignored
  `.env`. Map your own library names in `config/settings.yaml` to media categories
  and languages. The tracker uses Jellyfin's API to resolve item paths and library
  roots when the webhook omits a library name. Unknown libraries and API failures
  do not create logs.

Sources: [Jellyfin plugin installation](https://jellyfin.org/docs/general/server/plugins/),
[Webhook setup](https://jellyfin.org/docs/general/server/notifications/),
[Webhook variables](https://github.com/jellyfin/jellyfin-plugin-webhook/blob/master/README.md),
[payload builder](https://github.com/jellyfin/jellyfin-plugin-webhook/blob/master/Jellyfin.Plugin.Webhook/Helpers/DataObjectHelpers.cs),
[stable plugin manifest](https://repo.jellyfin.org/files/plugin/manifest.json).

---

## 1. Align library names

Edit `config/settings.yaml`:

```yaml
jellyfin:
  watch_threshold: 0.90
  library_map:
    Anime: anime
    JPDrama: show
    Movies: show
    Shows: show
  library_language:
    Anime: ja
    JPDrama: ja
    Movies: en
    Shows: en
  tadoku_default: pending
```

**Keys** must match Jellyfin **library names** exactly (case-sensitive).

---

## 2. Webhook plugin

1. Jellyfin Dashboard → **Plugins → Catalog** → install **Webhook**. Restart if asked.
2. Dashboard → **Plugins → Webhook** → **Add Generic**.
3. Configuration:

| Field | Value |
|-------|--------|
| Webhook URL (Jellyfin host → tracker) | `http://tracker.example:8000/api/webhooks/jellyfin` |
| Method | POST |
| Notification types | **Playback Stop** only |
| Item types | Episodes and movies |
| Headers | `Content-Type: application/json`, `X-Webhook-Secret: <WEBHOOK_SECRET>` |

Do **not** enable Playback Progress (spam) or Item Added.

**Secret** comes from this PC's ignored `.env` → `WEBHOOK_SECRET`. The header
keeps it out of URL logs; do not use the default `changeme`.

4. Template (JSON):

```json
{
  "NotificationType": "{{NotificationType}}",
  "ItemId": "{{ItemId}}",
  "Name": "{{json_encode Name}}",
  "SeriesName": "{{json_encode SeriesName}}",
  "ItemType": "{{ItemType}}",
  "SeasonNumber": "{{SeasonNumber}}",
  "EpisodeNumber": "{{EpisodeNumber}}",
  "RunTimeTicks": "{{RunTimeTicks}}",
  "PlaybackPositionTicks": "{{PlaybackPositionTicks}}",
  "PlayedToCompletion": "{{PlayedToCompletion}}",
  "Played": "{{Played}}",
  "Year": "{{Year}}"
}
```

`LibraryNameByMaxPath` is not a supported variable in the official plugin.
The tracker resolves the library from `ItemId`; do not insert a guessed
`LibraryName` (that would bypass the lookup).

5. Save. Finish an episode (played to completion or ≥ `jellyfin.watch_threshold`).

---

## 3. Aliases

Same as Plex: Catalog aliases map the Jellyfin title to `series_key` / `display_title`.
See [docs/PLEX.md](PLEX.md) §3.

---

## 4. Verify

```powershell
curl "http://127.0.0.1:8000/api/logs?source=jellyfin"
```

Jellyfin watches from libraries mapped to Japanese (currently Anime and JPDrama)
default to Tadoku mode **`auto`** (ready for automatic submission). Other
libraries stay **`pending`**. Toggle this on the tracker’s **Catalog / aliases**
page under **Jellyfin · Japanese libraries**; it affects future watches only.
Per-show Catalog Tadoku overrides (`auto`, `pending`, `never`) take precedence.

---

The end-to-end check is a real Playback Stop event after completing an episode.
The tracker has been tested against real Jellyfin item IDs without recording
fake watches; a plugin-triggered completion has not yet occurred.
