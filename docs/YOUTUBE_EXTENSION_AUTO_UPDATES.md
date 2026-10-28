# Automatic Firefox add-on releases

Verified against Mozilla primary documentation on October 28, 2026.

## Recommended path

Keep LiT unlisted and self-distributed. Build and validate a versioned Firefox
release, submit it to Mozilla for signing, then publish the signed XPI and an
update manifest on a stable HTTPS host. This preserves personal distribution.
Firefox supports this through `browser_specific_settings.gecko.update_url`.
[Mozilla update documentation](https://extensionworkshop.com/documentation/manage/updating-your-extension/)

The existing source and installed signed add-on use ID
`immersion-tracker-youtube@local.dev`, version `1.10.4`. Read-only Firefox
installation metadata confirms no update URL. Preserve the ID. A first signed build containing
the chosen update URL needs one manual installation. This bootstrap is an
inference from the current manifest and Mozilla's documented update behavior.

An alternative is a public AMO listing: Mozilla hosts updates automatically.
An installed self-distributed add-on without an update URL checks AMO for a
higher listed version. Unlisted signing alone does not provide hosted updates.
[Mozilla self-distribution rules](https://extensionworkshop.com/documentation/publish/self-distribution/)

## Release pipeline

1. Increment the version, run regression tests, and generate the existing
   Firefox-specific package using `scripts/pack-extension.ps1 -FirefoxRelease`.
2. Extract the generated package into a clean staging directory and lint it.
3. Run pinned `web-ext sign --channel=unlisted` against that directory, supplying
   credentials through `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET` environment
   variables. These are the AMO account's JWT issuer and secret. Current web-ext
   requires an explicit channel and the manifest's extension ID for updates.
   Signing downloads the signed XPI. Version 10 requires Node.js 22+.
   [Mozilla web-ext command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/)
4. Verify the signed artifact and upload it under an immutable versioned URL.
   Publish `updates.json` last so it never advertises an unavailable file.
   Atomic publication and immutable files are implementation recommendations.

Example update feed (placeholder host):

```json
{
  "addons": {
    "immersion-tracker-youtube@local.dev": {
      "updates": [{
        "version": "1.10.5",
        "update_link": "https://updates.example/lit/lit-1.10.5.xpi"
      }]
    }
  }
}
```

Host the feed over HTTPS. Use HTTPS for the XPI too. Firefox normally checks
daily; automatic updates are not immediate. Keep the feed URL durable because
existing installations cannot independently discover a replacement location.
[Mozilla update protocol and interval](https://extensionworkshop.com/documentation/manage/updating-your-extension/)

## Implemented release automation

`.github/workflows/lit-firefox-release.yml` runs on pushes to `main` that change
`extension/manifest.json`, or manually through Actions. Increment its version
for each release. It runs regression checks, builds the Firefox package, lints
with pinned web-ext 10.8.0, submits it for unlisted Mozilla signing, and publishes
the signed XPI to a versioned GitHub release. `scripts/publish-extension.ps1`
checks the signed artifact identity, update URL, and signing metadata; it makes
the update feed available only after checking the versioned download URL.

Stable feed URL:
`https://github.com/LucidPublicGit/immersion-tracker/releases/download/lit-firefox-updates/updates.json`

The public repository hosts downloads without authentication. Only release
packages include the feed URL; the development manifest remains unchanged.
Repository Actions secrets `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET` are
configured and successfully signed release 1.10.5. Do not ask the user to
recreate them unless authentication fails. Do not put their values in chat,
source files, or build archives. Release 1.10.5 includes the permission timing
correction.

After the first workflow succeeds, install its versioned signed XPI through
Firefox's **Install Add-on From File**. Keep the same add-on ID and verify
settings afterward. Future releases require a version bump and push; Firefox
then discovers them without another manual install. Test a subsequent release
using **Check for Updates** before considering the full path verified.

## Verified release and handoff — October 28, 2026

- [Release workflow 40648456419](https://github.com/LucidPublicGit/immersion-tracker/actions/runs/40648456419)
  completed successfully, including six regression checks, lint, Mozilla
  unlisted signing, versioned download publication, and feed publication.
- [Signed 1.10.5 XPI](https://github.com/LucidPublicGit/immersion-tracker/releases/download/lit-firefox-v1.10.5/lit-firefox-1.10.5.xpi)
  and the feed were fetched without authentication. The downloaded XPI's
  SHA-256 matched the feed; its manifest had the expected ID, version, and
  update URL, and Mozilla signature metadata was present.
- The signed file also exists locally at `dist/lit-firefox-1.10.5-signed.xpi`
  (gitignored). Prefer the public signed download for installation.
- The user was instructed to install this signed build once through Firefox's
  **Install Add-on From File**. If a temporary copy is loaded, restart Firefox
  first. Do not uninstall the permanent add-on or clear its saved settings.
- User completion of that installation, live history import after the fix,
  and an actual subsequent Firefox-driven update remain unverified.

For future extension fixes, bump the version and push to `main`; changes to
the manifest trigger the workflow. A manual workflow dispatch is available,
but do not resubmit an already-published version. Signing/review can delay
publication. Do not claim success until the workflow and anonymous feed/download
checks pass. Documentation-only changes do not trigger a release.
