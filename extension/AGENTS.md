# LiT extension releases

For extension changes intended for the installed Firefox add-on, increment
`extension/manifest.json` to a fresh version and push to `main` using
LucidPublicGit. The `Release LiT Firefox` Actions workflow automatically tests,
packages, lints, signs through Mozilla's unlisted channel, and publishes the
signed XPI and update feed. Do not stop after making a local ZIP when the user
expects their installed add-on to update. Watch the workflow result and verify
the published feed/download before reporting the release complete.

See `docs/YOUTUBE_EXTENSION_AUTO_UPDATES.md` for the pipeline, URLs, verified
release, and remaining browser verification. Preserve the add-on ID
`immersion-tracker-youtube@local.dev` and the stable feed URL. The packer adds
the update URL to Firefox release packages; the development manifest omits it.
Do not overwrite a published version or treat an unsigned XPI as signed.

Signing credentials already exist as repository Actions secrets
`WEB_EXT_API_KEY` (Mozilla JWT issuer) and `WEB_EXT_API_SECRET` (JWT secret).
Do not request them again unless signing reports an authentication problem.
Never print, commit, or package credentials or machine-local server overrides.

Run `node --test tests/extension-release.test.cjs tests/extension-updates.test.cjs`
from the repository root. Firefox permission requests must execute in the
original user input handler before awaiting storage or network operations.
The permission timing regression tests cover Save all and the shared history
permission helper.

Release 1.10.5 succeeded on October 28, 2026. The user received the signed
bootstrap install link; their installation and a subsequent browser-driven
update have not been observed. Future agents should check this if the user
reports that updates do not arrive. Do not remove the existing signed add-on
or clear its settings as a routine update step.
