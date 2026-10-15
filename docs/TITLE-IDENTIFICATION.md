# Incoming title identification

The main Inbox queue shows **Identify title** directly below supported titles,
including **Recent Tadoku logs**. Search, provider review, confirmation and
mapping removal stay in a dialog on the current page. The same action is also
available in Logs.

When automatic suggestions are enabled, the queue looks up up to eight distinct
unresolved source titles per page session, one request at a time. It reuses
previews for five minutes and avoids repeated requests during polling. It does
not load a model or save mappings automatically. A unique matching native title
or provider alias appears as **Suggested: … / Review suggestion**; other results
are shown as candidates needing review. **Accept suggestion** saves a unique
matching suggestion directly from the queue in one click; **Review suggestion**
opens the evidence dialog first. Ambiguous results have no accept button.
Search-text equality, including normalized
spacing/punctuation, is evidence to review, not identity approval.

Review the full title, medium, aliases and provider link, then choose **Use this
exact title**. That button saves the mapping for the same source, medium and full
original title. Related publications remain separate choices. Shared title
prefixes receive a warning; names or staff alone do not confirm the same work.

Confirmed Tadoku descriptions contain exactly the selected provider title, with
no appended volumes, episodes, editions, uploader tags or links. Original names
and provider links remain internal. Catalog keys, source references, counts,
volume fields and importer watermarks remain intact. Existing remote Tadoku
logs are never edited or resubmitted. Saved mappings work with AI/web lookup off,
including later Mokuro folds. **Remove mapping** restores original export behavior
for unsent logs sharing that source identity.

## Providers and examples

- Anime and manga: AniList, with native titles and strict medium filtering.
  Manga candidates exclude novels.
- Shows/drama, movies, books (novels/nonfiction/web novels), visual novels and
  games: Jiten's media-deck records, filtered to the corresponding medium and
  requiring a Japanese original-title field. Shows never fall back to anime decks.
- Podcasts, audiobooks, arbitrary YouTube videos and study logs are currently
  excluded where the available provider cannot sufficiently distinguish them.

Provider results include the native work title, medium, aliases and a link for review.

A provider's Japanese title is presented for review; it is not a claim that all
records have independently verified publisher/broadcaster spelling.

If search misses a work, paste a known provider link or numeric ID in the dialog.
For example, `https://anilist.co/manga/85802` or
`https://jiten.moe/decks/media/111215/detail`. The app validates the reference and
queries a fixed provider endpoint, checking the returned ID/medium/title.
Provider URLs are never fetched directly. No valid result means no proposed match.

## Configuration

- `TITLE_LOOKUP_WEB_ENABLED=false` by default enables/disables all provider lookup.
- `TITLE_LOOKUP_AUTO_SUGGEST_ENABLED=false` by default enables/disables queue
  prefetch and automatic search when opening the dialog. It also requires web
  lookup to be enabled. Configure deployment choices locally.
- **Use local AI suggestions** stays unchecked by default. E5 can compare a bounded
  set of provider titles/aliases on explicit request. It supplies known candidate
  IDs, never generated canonical names. Configure model location, prefixes,
  cutoffs, timeout, enable/disable and resource guards via [LOCAL-AI.md](LOCAL-AI.md).

Set environment options in `.env` and recreate the app with the Mac compose files.
Automatic lookup runs from the queue UI, not import polling. Disabling both web
and AI does not remove confirmed mappings or interrupt imports.

Failures, empty results and low-strength AI comparisons leave logs unchanged.
Editing search options clears/cancels old results. Previews expire after ten
minutes or app restart; changed source identities and unknown IDs are rejected.
This deployment uses one application worker. Multiple app workers would need a
shared preview signing key/store; otherwise preview confirmation can safely fail.
The additive `title_identities` table is created at normal startup.

## Validation

104 focused application tests pass, covering original provenance, exact exports,
future imports, importer folds, medium boundaries, provider failure, direct IDs,
stale/tampered previews and already-pushed idempotency. JS checks verify the
prefetch quota, deduplication and absence of automatic AI/save requests.

The live E5 Domestic Girlfriend comparison abstained at the existing conservative
cutoff. No threshold was lowered to force a result. This remains a manual-review
aid, not validated automatic cross-language identity detection.
