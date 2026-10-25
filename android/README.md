# Earth Empire for Android

`com.oeaio.earthempire`, Kotlin + Jetpack Compose (Material 3), minSdk 26, target 36. The same app
as `ios/` and the site in `web/`, over the API in [CONTRACT.md](../CONTRACT.md). Open source (MIT);
every dependency is open source (AndroidX/Compose/Media3, kotlinx, OkHttp, Coil - all Apache 2.0).

## What it shows

- **Home** (public): everything published, as infographics, not as an Instagram profile -
  key figures, a band of items per month, a map of places, tag and category bars, then the
  owner's **dedicated** sections ("About the owner") and the **common** ones ("Everything else"):
  one panel per highlight (plus "Detected and published" for the monitor hits the owner added, and
  "Posts and reels" for items in no highlight) with its counts, media, people (only names the
  posts themselves give, with the basis), places and key moments.
- **Feed**: any item or hit opens full screen in a vertical pager over the context it was tapped
  in (a panel, a month, a place, a tag, Detected). Videos autoplay muted; a tap unmutes. The
  overlay expands into the AI description and the analysis (people with basis, what, when,
  where, moments that seek the video, transcript, context). Share link; back returns to the same
  spot.
- **Detected**, **Status**, **Settings**: only after the owner's admin token is accepted by
  `GET /v1/admin/me` (the discreet key on Home). Detected lists `/v1/monitor/hits` by confidence
  (label, notes, judge, the suggested section and why), "+" publishes in a section (the
  suggestion first), "fetch N more". Status polls `/v1/status` every 10 s. Settings edits the
  phrases (variants and mishearings read-only), Save (rescans), Rescan, suggested phrases from
  the highlight names (accept/reject), the token, theme and data source.
- Offline: every API answer and every item seen is kept on disk and shown when the network
  fails; images and videos have disk caches. Pull to refresh everywhere. Light/dark/system.
  Content descriptions, headings, merged list rows and 48 dp targets for TalkBack.

**Provisional shapes** (read the same way as `web/src/sections.ts` / `web/src/live.ts` until
CONTRACT.md defines them): a highlight's part (`section`, `kind` or `dedicated`), a hit's
`section` and `suggested_section` (`"dedicated"` or `{"section", "reason"}`), `POST
/v1/monitor/hits/{id}/publish {"section"}`, `GET /v1/monitor/phrases/suggestions` and `POST
/v1/monitor/phrases/suggestions/reject {"text"}` (falls back to the highlight titles).

## Build and test

```sh
cd android
./gradlew testDebugUnitTest assembleDebug     # unit, Robolectric UI and screenshot tests; the APK
```

JDK 17+ (Android Studio's bundled JBR works; Gradle 9.1 runs on it). `local.properties` with
`sdk.dir` is not committed. Screenshot tests render with Robolectric's native graphics into
`app/build/screenshots/` (macOS or x86_64 Linux; skipped elsewhere).

`tools/box-build.sh` runs the same build on the AWS box (arm64): it has a JDK 17, the SDK in
`/srv/ee-android/sdk`, qemu-user + libc6:amd64 for Google's x86_64-only aapt2, and an x86_64 JDK
for the screenshot tests (`EE_SCREENSHOTS=1`).

Sample mode (Settings → Data) reads the bundled fixture (`app/src/main/assets/fixture/`, the iOS
app's) and a mock monitor, clearly labelled.

## App Links

The app opens `https://empire.earth/…` and `https://www.empire.earth/…` at the site's routes:
`/`, `/?q=`, `/item/<id>`, `/category/<slug>`, `/highlight/<id>?item=`, `/search?q=`, `/monitor`
and `/monitor/<hit id>` (owner), plus `earthempire://` with the same paths.

[`AppLinks/assetlinks.json`](AppLinks/assetlinks.json) is what the site serves at
`/.well-known/assetlinks.json` (the web build copies it; see `web/README.md`). It holds the
SHA-256 of a **debug** signing key for now. Debug keys differ per machine, so verification only
works for the build signed with that key; for the store, add the release key's fingerprint
(`keytool -list -v -keystore release.jks`) and, with Play App Signing, the app signing key's
from the Play Console.

## Release and Play Console (not done yet)

- A Google Play developer account (one-time fee) for the owner.
- A release keystore, kept outside this public repository: `keystore.properties` in `android/`
  (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`) is read by the build and ignored by
  git, as are `*.jks`/`*.keystore`. Enrol in Play App Signing and add its fingerprint to
  `assetlinks.json`.
- The listing: name, short and full description, icon (512 px), feature graphic, phone
  screenshots, privacy policy URL, data-safety form (no accounts; the admin token stays on the
  device), content rating, target audience.
- `versionCode`/`versionName` in `app/build.gradle.kts`, `./gradlew bundleRelease`, upload the AAB.
