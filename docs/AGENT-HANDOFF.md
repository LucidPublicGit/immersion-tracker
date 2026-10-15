# Optional local AI / title matching — implementation handoff

Read repository/root AGENTS.md before changes. Keep installation-specific
handoffs, runtime locations and deployment evidence in local private notes.

## Feature guides

- [Local AI settings and activity](LOCAL-AI-SETTINGS.md)
- [Incoming title identification](TITLE-IDENTIFICATION.md)
- [GSM matching and ignored sources](GSM-TITLE-MATCHING.md)
- [Native catalog comparison setup](LOCAL-AI.md)

## Implementation map

| Area | Main files |
| --- | --- |
| App switches and structured activity | app/media/ai_settings.py |
| Native encoder client / response validation | app/media/local_ai.py |
| Provider candidates / source identity / exact export title | app/media/title_identity.py |
| API settings, preview, confirmation | app/api/routes.py |
| Accepted mapping storage | app/db/models.py (`TitleIdentity`) |
| Tadoku export text | app/tadoku/client.py |
| Settings form / live activity | app/web/settings_ui.py |
| Queue/log suggestion, acceptance and review controls | app/web/title_identity_ui.py, app/web/queue_ui.py, app/web/logs_ui.py |
| GSM matching, source policy and local comparisons | app/api/gsm_games.py |
| GSM future sync exclusions / replay version handling | app/api/gsm_sync.py |
| GSM counting exclusions | app/ingest/gsm.py |
| GSM workbench / embedded queue dialog | app/web/gsm_games_ui.py, app/web/queue_ui.py |

## Preserve these boundaries

Automatic queue suggestions use provider APIs and text matching; local inference
is optional. The encoder compares known candidates and can abstain; it never
browses or supplies generated canonical names. Acceptance is explicit. Confirmed
Tadoku text is the exact work title, while original source names, counts, volume
fields, import watermarks and provider provenance remain internal. Existing
remote logs are not changed or resubmitted automatically.

GSM aliases are a separate identity system. Preserve original sentence IDs/text/
play times, old skip floors, arrival-time counting, version/replay markers and
pending-export guards. Ignore/discard is an explicit source-scoped webpage action;
original PC history remains unchanged.

Settings persist under data and apply without a rebuild. Native model controls
validate installed models/config revisions; keep resource guards fixed. Activity
is structured/bounded, without raw prompts, sentences or credentials.

Current follow-up is actual saved-map/source-import reuse, meaningful model
activity/off validation, GSM accepted-alias/ignore behavior and focused code review.
Do not force additional providers/models or revive completed SDK/report-only work.

## Delivery notes

Preserve local Mac compose networking configuration when updating the app.
Keep runtime configuration, databases, .env, credentials and user records out of
commits. Private pilot work stays local. No PR was created in this implementation.

Current focused verification: 153 app tests, seven private native runtime tests
and relevant JS checks passed. This is not a claim that the entire app suite passes.
Application code changes require a Mac mini build/restart using the Mac compose
files; markdown-only handoff updates do not require restarting services.
