# Collector

Reads the archived Instagram account through a real Chromium (Playwright) on the box, logged in as
a separate downloader account, and feeds the backend's ingest API (see `../CONTRACT.md`).

## What it collects

- **Profile:** name, bio, links, counts, avatar (re-hosted).
- **Posts, carousels, reels:** caption, hashtags, mentions, photo tags with positions (per carousel
  slide), location, music (or original audio), alt text, likes/comments/plays/views, and every label
  Instagram shows in `extra.labels`: pinned, edited, paid partnership, sponsors, collaborators, AI
  info, effects, comments/likes hidden, and so on. The whole source record, with CDN URLs removed,
  is kept in `extra.raw`.
- **Reels only in the Reels tab:** from `/api/v1/clips/user/`.
- **Highlights:** title, cover (re-hosted), order, and their stories in order. Every story carries
  the names of all highlights it is in (`highlights`), and those names are updated when a story is
  added to or removed from a highlight.
- **Stories:** current ones on every run, with stickers (mentions, hashtags, locations, links,
  polls, questions, sliders, quizzes, countdowns, music, shared posts, and others in `extra`).
- **Reposts:** a story that shares someone's post or reel gets `repost_of` with the original's author,
  caption, date, counts and media, re-hosted as `items/<id>/r<n>.<ext>`. Posts the account
  reposted from others (the profile's Reposts tab) become items `ig_repost_<original pk>`.
- **Media:** the largest image; for video the largest progressive MP4, or, when the DASH manifest
  has a taller stream, that stream muxed with the best audio by ffmpeg (no re-encode). Thumbnails
  are 640 px JPEGs. Everything goes through `POST /v1/ingest/media-url`; Instagram's CDN URLs are
  never sent.

## How it reads Instagram

`eecollector/igweb.py` keeps one persistent Chromium profile in
`/var/lib/earth-empire/browser/instagram/` (mode 700, holds `instagram.lock` while in use) and
reads Instagram's own JSON: the `/api/v1/` calls the web app makes, issued with `fetch()` from an
instagram.com page so they carry the session's cookies, CSRF token and app id, plus responses
intercepted while browsing (the Reposts tab). The parsers (`eecollector/parse.py`) take the v1 media
shape, which both the REST and the GraphQL (`xdt_api__v1__*`) responses carry.

Pacing and rate limits: see "Rate limits" below. A stable user agent
(the browser's own, without "HeadlessChrome") is stored in the profile, viewport 1366x900.

**Login.** Order: the saved profile; a Playwright `storageState` in the secret
`earth-empire/instagram-session` (if present); one automatic login with `earth-empire/instagram`
(TOTP if `totp_secret` is set), but only with `EE_AUTO_LOGIN=1` in `/etc/earth-empire/env` or
by running `ee-collector auto-login`; by default automation never types a password (CONTRACT.md). A checkpoint, a challenge, a two-factor prompt without a TOTP secret
or a refused login stops the run (exit 3 or 4) with a `STOPPED (...)` log line and a screenshot in
`/var/lib/earth-empire/collector/screenshots/`. After Instagram refuses the credentials, it never
tries an automatic login again until someone logs in by hand.

## On the box

`deploy/install.sh` (run as root by `backend/deploy/deploy-box.sh`, idempotent) installs a venv in
`/opt/earth-empire/collector-venv`, Chromium in the shared `/opt/earth-empire/ms-playwright`, the
`ee-collector` command, and the units below. Config comes from `/etc/earth-empire/env`
(`EE_API_URL`), secrets from Secrets Manager with the instance role.

```sh
aws ssm start-session --target <instance id>          # then, on the box:
ee-collector status                                   # items so far, cursors, login state
ee-collector incremental                              # one run now (as earth; the wrapper sudoes)
ee-collector sample                                   # gentlest run: one profile page view, then its newest video
sudo systemctl enable --now ee-collector-incremental.timer   # every ~45 min
sudo systemctl start ee-collector-backfill            # the whole account in one go, resumable
journalctl -u ee-collector-incremental -u ee-collector-backfill -f
ls /var/log/earth-empire/collector/                   # one log file per run
```

- **New items first.** Every run starts with a cheap check: the profile page's newest posts, the
  story viewer, the Reposts tab's first page, and highlights whose tray entry changed (or that were
  created since the last check). Anything newer than every earlier check saw, and any story added
  to a highlight, goes to the front of the timeline and is ingested before the backfill, marked
  `"priority": "new"` so the backend analyzes it first. During a long backfill the same check runs
  every ~10 minutes. Nothing is "new" on the very first run.
- **Order: by time, across every kind.** A run first lists, cheaply and without downloads: the
  profile page's posts, the Reposts tab (`user_reposts_timeline` grid items), the current stories
  (the story viewer at `/stories/<user>/`), every changed highlight's stories (the highlight viewer),
  and in a backfill the older feed and Reels pages from a saved cursor. Then it ingests one merged
  timeline, newest first: posts, reels, reposts, stories and highlight stories alike. The timeline
  is a table in `state.sqlite`, so the next run continues down it. A Reposts-tab item carries no date
  in the grid; it is placed by its pk's creation time and read in full with one request
  (`/api/v1/media/<pk>/info/`) when its turn comes. A failed step or item is logged and skipped;
  an item is dropped after three failures. Only a 429, a challenge or a lost session stops a run.
- **Backfill:** until a backfill has finished once, every timer run continues it for 40 minutes
  from its checkpoint (feed and clips cursors, highlights done), and refreshes stories every 45
  minutes meanwhile. So enabling the timer is enough; `ee-collector-backfill` (no time limit,
  restarts after a crash or rate limit, never after a checkpoint) just does it faster.
- **Incremental:** profile, current stories, highlights whose tray entry changed, the newest feed
  and Reels pages until a page has nothing new, the Reposts tab. Already uploaded media is never
  downloaded again.
- Every run ends with `POST /v1/ingest/runs` (ok, counts, `stopped_<kind>` when it stopped).
- **Status:** during a run it sends `POST /v1/ingest/heartbeat` (component `collector`) with what it
  is doing (`login`, `profile`, `stories`, `highlights i/n`, `posts n/m (downloads)`) and its
  progress, and an event when it finishes or stops (`STOPPED (login refused)`, `STOPPED
  (checkpoint)`, ...). Between runs `ee-collector-heartbeat.timer` (every 5 min, enabled by the
  install, no Instagram traffic) reports the last run's outcome, so `/v1/status` shows the
  collector as waiting or blocked rather than down.
- **Files:** durable state is `/var/lib/earth-empire/collector/state.sqlite` (items sent, media
  uploaded, highlight membership, cursors, login state, last run), covered by the backend's hourly
  backups. Screenshots there and the browser profile are not backed up; logs are in
  `/var/log/earth-empire/collector/`.

## Where it runs

On the box only. The SSM parameter `/earth-empire/collector/runner` names the machine allowed to
touch Instagram (`box`); a runner with another `EE_RUNNER` exits at once.

## Rate limits

12-30 s between Instagram requests, at most 80 an hour, a pause every ~20. The profile comes from
opening the profile page as a person would (its own responses and embedded data carry the user and
the newest posts). `web_profile_info` is never called; if the page yields no profile, the run stops
(`STOPPED (profile page gave nothing)`) without any API request. The
first 429 or "please wait" ends the run at once; then no run touches Instagram for 2 h, 4 h, 8 h, up
to 12 h after repeated ones (`ratelimit.until` in the state; `--force` overrides). A good run resets it.

## Logging in by hand (the remote view)

When a run stops for a checkpoint or a refused login:

```sh
# on the box
sudo systemctl start ee-remote-view
ee-collector login                     # headed Chromium on :99 with the collector's own profile
                                       # (or: sudo -u earth ee-browser-login instagram https://www.instagram.com/)
# on the Mac
aws ssm start-session --target <instance id> --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=6080,localPortNumber=6080
open http://localhost:6080/vnc.html
```

Log in, answer the challenge, choose "Save info". `ee-collector login` notices the session and
exits; the next run reuses it. Then `sudo systemctl stop ee-remote-view`.

Or log in on a Mac and hand over the session: save a Playwright `storageState` (cookies of
instagram.com) into the secret `earth-empire/instagram-session`, then `ee-collector import-session`
(or just wait: every run imports it when the profile is logged out).

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q
```

`tests/fixtures/` holds Instagram responses **written by hand from the documented shapes** of the
web API (v1 feed/user, clips/user, highlights_tray, reels_media, media/info, web_profile_info,
and the GraphQL timeline and highlights connections) with made-up accounts. Logged out, Instagram
no longer returns any media JSON (only experiment flags and "Unauthorized logged out query"), so
real ones could not be recorded that way. `EE_RECORD_DIR=<dir>` makes a live run save every raw
response for building new fixtures; scrub them before committing.

`tests/test_pipeline.py` runs the whole pipeline (fixture Instagram -> media -> upload -> upsert ->
highlights -> resume) against `tests/mock_backend.py` over HTTP. The mock also runs standalone:
`python tests/mock_backend.py --port 8787 --token test`, then
`EE_API_URL=http://127.0.0.1:8787 EE_INGEST_TOKEN=test ee-collector incremental`.

`deploy/look.py` opens a page with the profile, without typing anything, and prints what it shows.
