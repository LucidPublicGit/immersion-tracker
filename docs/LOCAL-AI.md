# Optional local catalog lookup

Quick log has a **Find similar titles** button when local catalog AI is enabled.
It runs only after a click, adds a conservative shortlist of existing rows of
the selected media type, and leaves the choice to the user. Normal title search
stays first. No row is automatically selected, created, merged or renamed;
logging still requires the normal user action.

The first adapter uses a locally installed SentenceTransformer-compatible
embedding model. The Mac worker owns each inference subprocess and exits it
after the request. The lightweight admission service keeps no model resident.
There is no new model HTTP endpoint or cloud fallback.

## Application settings

Defaults are off. Add these settings to the local `.env` when enabling:

```dotenv
LOCAL_AI_CATALOG_ENABLED=true
LOCAL_AI_CATALOG_HOST_SPOOL=/absolute/local/path/to/catalog-spool
LOCAL_AI_CATALOG_TIMEOUT_SECONDS=25
```

Deploy the Mac app with the optional overlay:

```sh
docker compose -f docker-compose.yml -f compose.mac.yaml -f compose.local-ai.yaml up -d --no-deps immersion-tracker
```

The overlay mounts only the worker's local request directory, at
`/run/local-ai-catalog`. It does not mount model weights or the private pilot
source into the app. `LOCAL_AI_CATALOG_SPOOL` is the corresponding in-container
path, set by the overlay. An absent worker, stale health, busy admission, timeout,
cancelled request or invalid response returns unavailable; normal search and
logging stay usable. The app timeout must be between 1 and 30 seconds.

Set `LOCAL_AI_CATALOG_ENABLED=false` and recreate the app to remove the button.
Deploying without the optional overlay also disables this integration.

## Model settings

The separate native runtime reads a JSON configuration file for every request.
For the installed Mac pilot, this is
`~/.local/state/local-ai/catalog-runtime.json`. It supports:

```json
{
  "enabled": false,
  "model_path": "/absolute/path/to/an/installed/embedding/model",
  "query_prefix": "query: ",
  "document_prefix": "passage: ",
  "minimum_similarity": 0.90,
  "maximum_score_drop": 0.01
}
```

Set `enabled` to false to turn inference off immediately. The app then shows
unavailable and continues normal search. Changing runtime settings during a
request cancels and discards that request. No app rebuild is needed for model
or prefix changes.

`model_path` must be an already installed, trusted, local compatible checkpoint.
The default pilot uses multilingual E5 small, CPU-only, with two threads and
the prefixes shown above. Other compatible embedding models can use different
paths and prefixes. Network downloads are disabled in the worker. A model that
is missing, incompatible or exceeds the resource budget produces unavailable.
Chat-generation checkpoints are not interchangeable with embedding checkpoints.

The similarity cutoff and score band are model-specific conservative filters,
not probabilities or calibrated accuracy. Check representative known titles,
ambiguous titles and no-match examples when changing them. A short or empty
list is preferable to forced suggestions. The default shortlist has up to five
rows, all within 0.01 of the best score and above 0.90. Title/alias search remains
the fallback when the model cannot meet those filters.

## Native worker lifecycle

The private Mac pilot owns `catalog_runtime.py` and its isolated Python
environment. The installed launch agent is `local.mini.local-ai-catalog`.
It watches the local spool and reloads configuration without loading models
while idle. Only titles, aliases, media type and opaque catalog IDs enter the
request. IDs are for validating returned rows; only title/alias text enters the
encoder. Notes, log text, credentials and metadata payloads are not sent.

The worker uses the existing resource guard: 8 GiB foreground headroom,
3 GiB job ceiling, CPU priority reduction, pressure/swap monitoring, pause/game
checks, and nonblocking pilot/subtitle locks. Failed jobs are terminated and
reaped. Results require successful exit and a final resource check. Scope such
as season, volume or edition is not inferred from vectors: qualified requests
stay on normal search because current catalog rows lack the necessary facts.

The app rejects unknown/duplicate IDs, changed catalogs, changed query/type,
nonfinite scores and stale responses. Query edits/type changes cancel pending
UI lookups; **Cancel lookup** does the same. Spool requests/results are transient
and abandoned files are removed within a minute. Runtime logs contain resource
status, not user query text.

To stop the native service on the installed Mac:

```sh
launchctl bootout gui/$(id -u)/local.mini.local-ai-catalog
```

To start it again:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.mini.local-ai-catalog.plist
```

The existing pilot's `resource_guard.py pause` also refuses inference. Resume
does not bypass headroom, swap, pressure or cooldown checks.

## Initial validation and limits

The new client/route tests cover disabled, busy, cancelled, stale and malformed
results, source changes and no catalog mutation. Native runtime tests cover
request bindings, deadlines, incompatible configuration, cutoff behavior and
disabled admission. Live Docker-to-Mac and tailnet-browser checks found the
expected Code Geass and Eizouken rows. Weak/unrelated requests returned no extra
suggestions; a season-qualified request refused model lookup. The default score
band was narrowed after an unrelated Rainbow neighbor appeared in the initial
Code Geass development check. These are small development/functional checks,
not a representative accuracy score. Only manual suggestions are supported.

The live launch-agent jobs sampled about 0.96 GiB peak RSS, unchanged swap and
successful model-worker exit. The lightweight idle service sampled about
25 MiB RSS. Current lookups can take around 16 seconds on the launch agent;
they run outside the application's normal search/logging path and are cancellable.

The broader app suite has eight failures that also reproduce on the existing
pre-change image; the nine new local-AI tests pass. No new inference packages
were added to the app. The initial deployment reused the installed dependency
image because the macOS Docker credential helper was locked; normal dependency
rebuilds still use the repository Dockerfile and Mac compose files after that
credential-helper issue is resolved. No authentication settings were changed.

## Incoming source titles

The same optional native worker can suggest among bounded AniList work
candidates in **Identify title**. Web lookup has its own off switch; confirmed
mappings work offline. See [TITLE-IDENTIFICATION.md](TITLE-IDENTIFICATION.md) for
exact Tadoku titles, retained original names and configuration.
