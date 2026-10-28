# Mozilla reviewer instructions — 1.10.4

This is an unlisted personal companion to the open-source Immersion Tracker
server, not an independent YouTube service. No purchase is required. The
extension uses readable, unminified JavaScript with no dependencies or remote
executable code. It reads YouTube's page/session data for watch tracking and
user-initiated history import.

## Reproduce the submission

With PowerShell and the source tree, run:

```powershell
./scripts/pack-extension.ps1 -FirefoxRelease
```

Upload `dist/immersion-tracker-youtube-firefox-unsigned.zip`. The packer copies an
explicit set of files and generates a Firefox manifest: desktop minimum 140,
Android minimum 142, data collection categories, no Chromium service worker,
no remote HTTP optional permissions, and private browsing disabled. The add-on
ID stays `immersion-tracker-youtube@local.dev`. No compilation or minification is
performed. Per-machine overrides and credentials are excluded.

## Functional verification

1. Install in Firefox desktop 140+ and accept the displayed data permissions.
2. Open Settings. Privacy explains watch metadata, account/history access, local
   storage, authentication, recipients, and controls.
3. Configure your own test Immersion Tracker instance, using its HTTPS origin
   and test webhook secret. For a server on the same machine, HTTP localhost is
   supported. A remote HTTP URL must be rejected without sending a request.
   Server setup is documented in the repository README. Production instance
   addresses, credentials, and user records are intentionally not supplied.
4. Choose Test server. It should report a healthy server. Pin the toolbar icon.
5. Visit a YouTube video. Configure viewer/language/channel filters for the test
   account. Use a short minimum-watch setting and watch past the configured
   threshold. Confirm one log appears in Activity and the tracker. Repeat the
   same video and confirm deduplication.
6. Choose Log from history while signed in to a YouTube test account. Scan, review
   candidates, approve one, and confirm it logs. Reject another and rescan.
7. Open the legacy `import.html` extension page and confirm it redirects to
   Activity's From history section without inline scripts.
8. Fully restart Firefox and confirm the signed add-on remains installed.

If reviewing without a tracker server, the settings, privacy page, YouTube tab
detection, unreachable-server state, and rejection of remote HTTP can still be
checked. End-to-end logging requires the separate tracker; contact the submitter
through AMO if additional testing access is needed.

## Local verification

```powershell
node --test tests/extension-release.test.cjs
npx --yes web-ext@latest lint --source-dir <extracted-submission-folder>
```

Regression checks cover refusing remote plaintext requests before transmitting
credentials, refusing redirects, accepting HTTPS requests with API query strings,
and rendering restored history metadata as plain text rather than executable HTML.
