# Local AI settings and visibility

Open **More → Settings** (`/settings`). The focused Local AI section provides:

- Enable local AI comparison.
- Enable title provider lookup.
- Automatically suggest queue titles.
- Installed embedding model folder and minimum similarity.
- An advanced fold for model-specific query/title prefixes.

These app switches persist in `data/local-ai-settings.json` and override the
`.env` defaults. Saved settings take effect without rebuilding the app. Refresh
an open queue tab when changing its automatic-suggestion option. Model controls
are validated by the native worker: select an already-installed Sentence
Transformers compatible embedding model on that host. No model is downloaded
or run by saving settings. Unknown fields, missing model folders and stale
configuration revisions are rejected. CPU/memory/foreground-work guards remain
fixed and are not editable from this page.

The native worker bridge remains opt-in through `compose.local-ai.yaml`. If it
is offline, app switches still work; model controls remain unavailable until the
worker is back. This setup uses an embedding encoder (E5 currently), not a chat
LLM or an autonomous browsing agent. It does not accept a generative API endpoint.

## What suggestions do

1. Queue title lookup sends a cleaned search hint and medium to AniList or Jiten.
   The app compares the returned titles and aliases. Automatic queue suggestions
   use this provider lookup, without local inference.
2. When explicitly requested, the local encoder compares the query with known
   candidate titles/aliases. It returns only IDs from that set and can abstain.
   The model does not query provider APIs or generate a canonical title.
3. Accepting a title saves a source mapping; existing remote Tadoku logs remain
   untouched. Saved mappings work with provider lookup and AI off.
4. GSM suggestions compare source names with the stored shared game's names.
   Its optional local AI comparison uses those existing game rows, without web
   provider lookup. Accepted GSM aliases automatically apply to future uploads.

## Activity view

Recent activity polls every four seconds while the page is visible. Turn off
**Live updates** to pause it. Entries distinguish provider API lookup, optional
local comparison, source mapping and GSM source-policy actions. The native tail
reports its last jobs, result count/abstention, elapsed time and peak memory when
available. Native status shows offline, disabled, busy or idle. Models unload
after each job; the lightweight admission service stays running.

This is a bounded structured tail, not raw process output. It excludes credentials,
source sentence text, raw model prompts and arbitrary host logs. App activity
covers the current process session; native worker activity retains its last
30 jobs in the spool. Logging/polling alone never starts inference.
