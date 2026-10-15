# GSM title matching and ignored sources

From Inbox's GSM section, choose **Match / ignore GSM titles**. The workbench
opens in a dialog; `/gsm-games` remains available directly.

Stored game names provide automatic suggestions. A unique exact normalized name
or alias gets **Accept suggestion**. The server rechecks uniqueness and the
current candidate before applying it. Approximate similarities are for review;
rounded scores are never treated as exact names. Accepted aliases associate
existing shared history and future uploads with the selected game. Original
sentence IDs/text/play times and already-excluded history stay intact.

**Compare with local AI** optionally runs the configured native encoder against
those stored games. It does not call web APIs or silently change associations.
An unavailable model or weak result leaves matching manual. Model and provider
work is explained in [the settings guide](LOCAL-AI-SETTINGS.md).

## Ignore or discard

Each source has **Ignore title** and **Discard local history** actions:

- Ignore keeps local history but excludes it from counting and normal review.
  Future uploads with that exact source name are skipped in the tracker's shared
  copy. Other source names are unaffected.
- Discard also deletes the matching local shared-history rows. It keeps version
  markers so duplicate or old sync events cannot resurrect discarded rows.
  The source remains ignored for future arrivals.
- **Ignored titles → Stop ignoring** enables future arrivals again. It does not
  restore discarded history or recount already-exported material.

Each action previews the source/count and requires confirmation in the webpage.
Changed source history and pending GSM exports prevent the action until reviewed.
These actions do not delete history on the original PCs or edit past Tadoku logs.

`(unnamed source)` is a display label for GSM records whose `game_name` is empty
or NULL. It is not an identified title. The workbench explains that origin and
allows ignoring/discarding it. Ignoring a source retains its history until the user explicitly discards it.
