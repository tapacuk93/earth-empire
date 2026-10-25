# Earth Empire — contract between the parts

An archive of one Instagram account (the owner's), mirrored to **https://empire.earth**, an iOS
app **Earth Empire**, and the owner's X account. Claude, on the backend, sorts every item into
categories.

One public repository, github.com/tapacuk93/earth-empire - so no secret, password, token or
account detail is ever committed; they live in AWS Secrets Manager.

| Folder | Owns |
|---|---|
| `backend/` | AWS infra, the database, the API at `api.empire.earth`, analysis and categories with Claude, the X poster, deploys (including the site's hosting) |
| `collector/` | the headless browser in AWS that reads the account and feeds the API |
| `web/` | the site at `empire.earth` - a static app over the API, every browser and screen size |
| `ios/` | the iOS app Earth Empire (`com.oeaio.earthempire`) over the API |
| `monitor/` | the monitor: public videos of official (and followed, reposted, recommended) accounts, transcribed on the box and searched for the owner's phrases and out-of-place Ukrainian/Russian; its API under `/v1/monitor/` and `/v1/published` |

Each part changes only its own folder. This file is shared; change it only together with every
part that reads it.

## Infrastructure

- AWS account 798762732010, region `us-east-1`. Tag everything `project=earth-empire`.
- DNS: `empire.earth` is registered at GoDaddy and today serves GoDaddy's "Coming Soon" page (no
  MX, no TXT). A Route 53 hosted zone `empire.earth` holds the records; the owner switches the
  domain's nameservers at GoDaddy to the zone's four. Until then everything is tested on the AWS
  hostnames.
- `empire.earth` and `www.empire.earth`: the site, from S3 behind CloudFront.
- `media.empire.earth`: media files, from S3 bucket `earth-empire-media` behind CloudFront.
  Keys: `items/<item id>/<n>.<ext>`, `items/<item id>/<n>.thumb.jpg`, `highlights/<id>/cover.jpg`,
  `profile/avatar.jpg`.
- `api.empire.earth`: the API.
- Secrets in AWS Secrets Manager, never in git:
  - `earth-empire/instagram`: `{"username", "password", "totp_secret"?}` of the *downloader* account
    (a separate account; the archived account is public).
  - `earth-empire/target`: `{"username"}`, the archived account.
  - `earth-empire/ingest-token`: a random string; the collector sends it as `Authorization: Bearer`.
  - `earth-empire/x`: X API credentials (OAuth 1.0a user context: api_key, api_secret,
    access_token, access_secret; or OAuth 2.0 user tokens).
  - `earth-empire/facebook-session`: a Playwright `storageState` JSON for the owner's Facebook login.
  - `earth-empire/admin-token`: a random string, the owner's token for owner-only endpoints
    (`Authorization: Bearer`). The apps ask for it once, check it with `GET /v1/admin/me`, and keep
    it in the Keychain or local storage. It is never shown or logged.
  - `earth-empire/claude`: how the backend reaches Claude (the aicoin proxy and a server wallet
    token, or an Anthropic key).

### The box

One EC2 instance runs the API, the workers, the collector and the browsers. Its details beyond
these live in `backend/README.md`.

- `t4g.medium` (arm64, 2 vCPU, 4 GB, plus 4 GB swap), Ubuntu 24.04, tags `Name=earth-empire` and
  `project=earth-empire`. Reached with SSM only, never SSH: `aws ssm start-session --target <id>`,
  with the id from `aws ec2 describe-instances --filters Name=tag:Name,Values=earth-empire`.
- The repository is checked out at `/opt/earth-empire/repo` and owned by the user `earth`, which
  runs every service. A deploy (`backend/deploy/deploy-box.sh`) pulls `main`, then runs
  `<part>/deploy/install.sh` as root for every part that has one. That script is idempotent and
  installs that part's dependencies and systemd units.
- Data lives in `/var/lib/earth-empire/<part>/`, and config not in git in `/etc/earth-empire/env`
  (`EE_API_URL=http://127.0.0.1:8000` for parts on the box, `EE_PUBLIC_API_URL`,
  `EE_MEDIA_BASE_URL`, `AWS_REGION`). Secrets are read from Secrets Manager with the instance
  role, never written to disk.
- Playwright's browsers are shared in `/opt/earth-empire/ms-playwright`
  (`PLAYWRIGHT_BROWSERS_PATH`); `ffmpeg` is installed.
- **Browser profiles** (logged-in sessions) live in `/var/lib/earth-empire/browser/<name>/`, mode
  700, never in git or S3. `<name>` is `instagram` or `facebook`. Only one process may use a profile
  at a time: hold `flock /var/lib/earth-empire/browser/<name>.lock` while using it.
- **Remote view** for the owner to log in by hand: the service `ee-remote-view` runs an X display
  `:99` (Xvfb), x11vnc and noVNC, listening on `127.0.0.1:6080` only. A browser that needs a human
  runs headed on `DISPLAY=:99`. `sudo -u earth ee-browser-login <name> <url>` takes the profile's
  lock and opens Chromium with it on that display, and the owner opens the view through SSM port
  forwarding (steps in `backend/README.md`). Automation never types a password or solves a
  challenge: when a session is logged out or a checkpoint appears, it stops, logs it, saves a
  screenshot and waits for the owner.
- **State survives a rebuild.** Durable state goes in SQLite files (`*.sqlite`, `*.sqlite3`, `*.db`)
  under `/var/lib/earth-empire/<part>/`, at most two levels down. The backend backs up every one of
  them hourly, consistently, to the private bucket `earth-empire-backups` (`state/latest/...`, plus a
  daily copy kept 35 days). A fresh box restores them before any service starts, and
  `ee-restore-state [date]` restores by hand. Caches, screenshots and browser profiles are not
  backed up.
- **Heartbeats:** a long-running part reports itself to `POST /v1/ingest/heartbeat` (see "The API"),
  every few minutes and when its state changes, so `GET /v1/status` can show it.
- **Systemd units** are named `ee-*`.

## The data

Every id is a string. Times are ISO 8601 UTC. Everything the source shows is kept: when in doubt,
store it in `extra`.

```jsonc
// Item
{
  "id": "ig_<instagram media pk>",
  "kind": "post" | "carousel" | "reel" | "story",
  "shortcode": "C1a2b3c" | null,           // stories have none
  "source_url": "https://www.instagram.com/p/…/" | null,
  "taken_at": "2024-05-01T12:00:00Z",
  "caption": "…" | null,
  "hashtags": ["…"], "mentions": ["…"],    // from the caption, without # / @
  "tagged_users": [{"username": "…", "x": 0.5, "y": 0.3}],   // photo tags, positions if given
  "location": {"name": "…", "id": "…", "lat": 0, "lng": 0} | null,
  "music": {"title": "…", "artist": "…"} | null,
  "alt_text": "…" | null,
  "stickers": [{"type": "mention|hashtag|location|link|poll|question|music|…", "text": "…", "extra": {}}],  // stories
  "counts": {"likes": 0, "comments": 0, "views": 0, "plays": 0},  // whatever is visible, else absent
  "media": [{
    "type": "image" | "video",
    "url": "https://media.empire.earth/items/<id>/0.mp4",
    "thumbnail": "https://media.empire.earth/items/<id>/0.thumb.jpg",
    "width": 1080, "height": 1920, "duration": 12.3 | null,
    "cover": "https://media.empire.earth/items/<id>/0.cover.jpg" | null,  // video only, set by the backend:
    "cover_at": 4.5 | null                 // the best-looking frame (sharp, representative) and its time in s
  }],
  "highlights": [{"id": "hl_<pk>", "title": "Travel"}],   // every highlight this story is in
  "repost_of": null | {                    // a story or post that shares someone's reel or post
    "author": "username", "author_name": "…",
    "shortcode": "…", "source_url": "https://www.instagram.com/reel/…/",
    "taken_at": "…", "caption": "…",
    "media": [/* as above, re-hosted on media.empire.earth */]
  },
  "categories": ["travel", "food"],        // slugs; set by the backend, never by the collector
  "summary": "one sentence" | null,        // set by the backend
  "description": "…" | null,               // set by the backend: a few sentences on who, what, when,
                                           // where and context, written to be published and shown
                                           // by the site and the app; for a repost it covers the original too
  "analysis": null | {                     // set by the backend - see "Analysis" below
    "people": [{"who": "@username" | "a name" | null, "description": "…", "basis": "tag|mention|caption|speech|on-screen text|description only", "role": "…", "appears": [{"media": 0, "from": 1.5, "to": 8.0}]}],
    "what": "what is happening, in a few sentences",
    "events": [{"media": 0, "at": 3.2, "text": "…"}],    // moments in a video
    "when": {"date": "…", "time_of_day": "…", "season": "…", "occasion": "…", "basis": "…"},
    "where": {"place": "…", "kind": "beach|city|home|…", "country": "…", "basis": "location|caption|landmark|signage|…"},
    "objects": ["…"], "animals": ["…"], "brands": ["…"],
    "on_screen_text": ["…"],
    "speech": {"language": "…", "transcript": "…"} | null,
    "music": "…" | null,
    "mood": "…", "language": "…",
    "context": "anything else worth knowing - why it was posted, what it refers to, series it belongs to",
    "keywords": ["…"],
    "model": "…", "analyzed_at": "…"
  },
  "extra": {},                             // anything else the source had
  "collected_at": "…", "updated_at": "…",
  "published_at": "…"                      // set by the backend when the item went public (see "The pipeline")
}

// Highlight
{"id": "hl_<pk>", "title": "Travel", "cover": "https://media.empire.earth/highlights/<id>/cover.jpg",
 "item_ids": ["ig_…"], "updated_at": "…"}   // item_ids in the highlight's own order

// Category
{"slug": "travel", "name": "Travel", "description": "…", "count": 42}

// Profile
{"username": "…", "full_name": "…", "bio": "…", "avatar": "https://media.empire.earth/profile/avatar.jpg",
 "links": ["…"], "counts": {"posts": 0, "followers": 0, "following": 0}, "updated_at": "…"}
```

## The API (`https://api.empire.earth`, JSON, CORS open for GET)

Public, read-only:

- `GET /v1/profile` → Profile
- `GET /v1/items?kind=&category=&highlight=&tag=&q=&before=&limit=` → `{"items": [Item], "next": "<cursor>" | null}`;
  newest first; `q` searches captions, summaries, descriptions, hashtags, locations, highlight titles
  and the analysis; `tag` matches a tag from `/v1/tags` (case-insensitive, any kind).
- `GET /v1/items/{id}` → Item
- `GET /v1/highlights` → `{"highlights": [Highlight]}`, in the profile's order
- `GET /v1/categories` → `{"categories": [Category]}`, by count
- `GET /v1/tags?kind=&limit=` → `{"tags": [{"tag": "beach", "kind": "keyword", "count": 12}]}`, by
  count, for a tag cloud. Tags come from published items' analyses and captions, and are lowercase.
  `kind` is one of `category`, `keyword`, `place`, `country`, `object`, `animal`, `brand`,
  `hashtag`, `person` (only people the post itself named: tag, mention or caption), `mood` or
  `occasion`. The same tag can appear under two kinds.

Ingest, for the collector only (`Authorization: Bearer <earth-empire/ingest-token>`):

- `POST /v1/ingest/media-url` `{"key": "items/<id>/0.mp4", "content_type": "video/mp4"}` →
  `{"upload_url": "<presigned PUT>", "public_url": "https://media.empire.earth/…"}`
- `PUT /v1/ingest/items` `{"items": [Item without categories/summary]}`: an upsert by id. A
  repeated item updates its fields and keeps its categories unless its caption or media changed.
- `PUT /v1/ingest/highlights` `{"highlights": [Highlight]}`: the upsert.
- `PUT /v1/ingest/profile` Profile
- `POST /v1/ingest/runs` `{"started_at", "finished_at", "ok": bool, "counts": {}, "log_url"?}`:
  one record for each collector run, for health checks.
- `POST /v1/ingest/heartbeat`
  `{"component": "collector" | "monitor" | …, "ok": bool, "error"?: "…", "detail"?: {k: number|string|bool},
  "jobs"?: [{"what", "progress", "started_at"}], "event"?: "…", "kind"?: "…"}`. This is how a part
  appears in `/v1/status`; a part that has not sent one in 30 minutes shows as `down`. Keep
  `detail` and `jobs` free of secrets and private data, since they are shown publicly (scrubbed
  again on output).

Status, **owner only** (`Authorization: Bearer <earth-empire/admin-token>`; 401 without it).
`GET /v1/health` stays public and says only `{"ok": true}`.

- `GET /v1/status` →
  ```jsonc
  {"generated_at": "…", "overall": "ok" | "degraded" | "down",       // over api, db, workers, analyzer, collector
   "components": [{"id": "api" | "db" | "workers" | "analyzer" | "collector" | "monitor" | "x_poster" |
                          "facebook_poster" | "site" | "disk" | "memory" | "cpu" | "queues" | <a heartbeat part>,
                   "name": "…", "state": "ok" | "degraded" | "down" | "off",     // off: switched off on purpose
                   "last_success": "…" | null, "last_error": {"at": "…", "message": "…"} | null,
                   "details": {…}}],                                   // per component; queues: {step: {state: n}}
   "activity": {"jobs": [{"component", "what", "item": "<id>" | null, "progress", "started_at", "elapsed_s"}],
                "events": [{"at", "component", "kind", "text", "item": "<id>" | null, "ok": bool}]}}  // newest 50
  ```
  Even for the owner, nothing secret appears: error texts are scrubbed, and `item` is set only for
  items that are already public.

Owner-only (`Authorization: Bearer <earth-empire/admin-token>`):

- `GET /v1/admin/me` → `{"ok": true, "role": "owner"}`, or 401: checks a token the owner entered.
- `GET /v1/admin/pipeline` (the ingest token works here too), `GET /v1/admin/items/{id}`
  (the item whatever its state, with its steps and transitions), `POST /v1/admin/items/{id}/reanalyze`.

## Analysis

The backend analyzes every item, both the existing ones and each new one as it arrives (and the
original of a repost too). Claude sees all of the following:

- frames sampled across every video, with their timestamps;
- every image;
- a transcript of the speech;
- the caption, tags, mentions, stickers, location, music, date, highlight names;
- the account's earlier items, for recurring people, places and series.

From these it writes `analysis`, then `categories`, `summary` and `description`, the tags, and a
cover for each video: the best-looking sampled frame, saved at full size as
`items/<id>/<n>.cover.jpg` (`items/<id>/r<n>.cover.jpg` for a repost original's media `n`).

- **Who:** people are named only from what the post itself says - photo tags, mentions,
  caption, speech, on-screen text - or from a name the owner gave to a person in earlier items. A
  face is never identified by its looks. Otherwise the person is described, not named.
- **Re-analysis:** an item is analyzed again when its media or caption changes, or when the owner
  asks.
- **Search:** `q` searches the analysis too.

## The pipeline

Every item goes through these steps in order. The backlog goes oldest first, and each new item
goes through as it arrives. Each step has its own recorded state, and a failure retries with
backoff without blocking other items. Every transition is logged.

1. **Downloaded:** the collector has ingested it (a post, carousel, reel, story, highlight story, or
   a repost together with its original).
2. **Analyzed:** the backend has written `analysis`, `categories`, `summary` and `description`.
   The public API shows an item only from this point on. `published_at` is when that happened.
   Analysis spends money, so the backend caps how many items it analyzes per day. The owner raises
   the cap to work through the backlog.
3. **Published** to each destination, with its own state for each: `pending`, `posted` (with the
   destination's id or URL), `failed` (with the reason), or `skipped`. The destinations are:
   - `site`: empire.earth and the app, which happens on reaching step 2;
   - `x`: the X API;
   - `facebook`: the browser session.

   A post on X or Facebook carries the description, the original caption, the date, the highlight
   names, the categories as hashtags, and the repost credit.

`GET /v1/admin/pipeline` (admin or ingest token) returns the counts in each state and the latest
failures; `GET /v1/status` (owner only) shows the same, scrubbed.

## Monitor

The apps' main mode. `monitor/` watches public videos, transcribes them on the box (faster-whisper,
language identified per chunk) and flags two kinds of **hit**:

- `name`: a word or words that sound like one of the owner's **phrases** (any grammatical form,
  transliteration or likely mishearing, fuzzy and phonetic, Latin and Cyrillic);
- `language`: Ukrainian or Russian speech (a few seconds or more) in a source whose expected
  languages do not include it.

No hit is ever certain. Low-confidence hits are kept (recall over precision), labelled, and always
carry the excerpt so a person can judge. The monitor is its own service on the box
(`ee-monitor-api` on 127.0.0.1:8010, `ee-monitor-worker`); nginx routes `/v1/monitor/` and
`/v1/published` to it behind the same CloudFront. State: `/var/lib/earth-empire/monitor/`.

Sources have a `source_kind`: `official` (the registry `monitor/sources.json`, and accounts the
owner adds), `followed` (accounts tapacuk93 follows), `reposted_author` / `reposted` (the owner's
Instagram reposts and their authors) and `recommended` (what a platform suggests next to a seed;
`via` names the seed: a hit id or a backend item id, at most `rec.max_hops` hops away).

```jsonc
// Hit
{
  "id": "h_…",
  "kind": "name" | "language",
  "phrase": "тарас маслов" | null,          // name hits: which phrase matched
  "matched": "Тарасом Масловим",            // the words as transcribed; for language hits "uk" | "ru"
  "confidence": 0.62,                       // 0..1, sort key by default
  "confidence_label": "likely" | "possible" | "low confidence",   // >=0.7, >=0.4, below; never "certain"
  "scores": {"sound": 0.9, "asr": 0.8, "name": 0.85},   // name: how it sounds, Whisper's word probability,
                                            // name-vs-common-word; language: {"language", "script", "duration", "speech_s"}
  "notes": ["a form of 'тарас'", "may be a quoted clip…"],   // why, and why it may be a coincidence
  "judge": {"by": "claude", "name_probability": 0.7, "reason": "…"} | null,
  "language": "ru",                         // the language of the speech around it
  "expected_languages": ["en"],
  "platform": "telegram" | "youtube" | "facebook" | "instagram" | "x" | "web",
  "source_kind": "official" | "followed" | "reposted_author" | "reposted" | "recommended",
  "via": "h_…" | "ig_…" | null, "hop": 0,
  "source": {"id": "ru_mid", "name": "Ministry of Foreign Affairs of Russia", "kind": "ministry",
             "country": "RU", "source_kind": "official"},
  "account": "MID_Russia",
  "video": {"id": "tg:MID_Russia/94660", "url": "https://t.me/MID_Russia/94660", "title": "…",
            "posted_at": "…", "duration": 83.0, "thumbnail": "…" | null},
  "start": 12.4, "end": 13.1,               // seconds into the video
  "at_url": "https://t.me/MID_Russia/94660?t=10",   // opens near the moment where the platform supports it
  "excerpt": {"text": "…", "start": 6.4, "end": 19.1, "language": "ru", "en": "…" | null},
  "clip": "https://…" | null,              // <= 20 s around the hit; see "Monitor media" below
  "frame": "https://…" | null,
  "model": "faster-whisper small int8", "found_at": "…",
  "published_at": "…" | null                // set by the owner's publish
}
```

**Only the apps' Home screen is public.** Detected (hits), Status and Settings are the owner's.

Public (CORS open):

- `GET /v1/published` → `{"hits": [Hit], "next"}`: the hits the owner published, newest first, for the
  apps' Home screen. Their `clip`/`frame` are public URLs under `media.empire.earth/monitor/public/`.
- `GET /v1/items…`, `/v1/highlights`, `/v1/categories`, `/v1/tags`, `/v1/profile`, `/v1/health` (see "The API").

Owner only (`Authorization: Bearer <earth-empire/admin-token>`, via the same check as the backend's
`require_admin`; 401 without it), everything else under `/v1/monitor/`:

- `GET /v1/monitor/hits?kind=name|language&platform=&source_kind=&phrase=&min_confidence=&published=true|false&sort=confidence|recent|posted&before=<cursor>&limit=`
  → `{"hits": [Hit], "next": "<cursor>" | null}`; by confidence (highest first) unless `sort` says otherwise.
- `GET /v1/monitor/hits/{id}` → Hit
- `POST /v1/monitor/fetch {"n": 10, "platform"?: "…", "source_kind"?: "…"}` → `{"request_id", "n",
  "queued", "to_discover"}`: queue at least `n` (max 50) more videos to scan, newest unscanned first,
  spread over sources; what is not yet discovered is looked for further back. Within the daily caps;
  `429` when the queue is full.
- `GET /v1/monitor/sources?platform=&source_kind=` → `{"sources": [{"id", "name", "kind", "country",
  "source_kind", "origin", "source_url", "expected_languages", "languages_inferred", "accounts":
  [{"id", "platform", "handle", "platform_id", "enabled", "last_polled_at", "last_error", "videos", "scanned"}]}]}`
- `GET /v1/monitor/phrases` → `{"phrases": [{"text", "variants": ["…"], "mishearings": ["…"],
  "claude_variants": ["…"], "updated_at"}]}`
- `GET /v1/monitor/videos?state=&platform=&limit=` → recent videos and their scan state
  (`new | queued | running | done | failed | blocked | skipped`, with `error`, `languages`, `hits`).
- `GET /v1/monitor/status` → queue by platform and state, totals, throughput (`cpu_per_audio`),
  today's usage against the caps, open fetch requests, and `stops` (a platform paused by a
  checkpoint, warning, login or billing refusal, with the reason).
- `POST /v1/monitor/hits/{id}/publish`, `POST /v1/monitor/hits/{id}/unpublish` → Hit
- `PUT /v1/monitor/phrases {"phrases": ["тарас", "тарас маслов", "маслов"], "claude"?: true, "rescan"?: true}`
  → as GET. Replaces the list; variants are generated by rule, Claude adds spellings once per new
  phrase (cached), and stored transcripts are matched again (`rescan`).
- `POST /v1/monitor/rescan` → `{"ok", "videos"}`: detection again over every stored transcript.
- `POST /v1/monitor/sources {"name", "platform", "handle", "expected_languages"?, "kind"?, "country"?, "channel_id"?}`
  → `{"source_id", "account_id"}`

**Monitor media.** A clip or frame of an unpublished hit must not be reachable by guessing a URL. The
media CDN refuses every path under `/monitor/` except `/monitor/public/` (403, enforced in the
backend's stack). So:

- The monitor stores clips and frames privately in S3 under `monitor/clips/` and `monitor/frames/`.
  In owner responses, an unpublished hit's `clip`/`frame` are presigned S3 GET URLs (at most 1 hour).
- On publish, the monitor copies them to `monitor/public/<hit id>.<ext>`, and the hit's URLs become
  `https://media.empire.earth/monitor/public/…`. On unpublish, it deletes those copies and
  invalidates `/monitor/public/<hit id>.*` on the media distribution (the box role may).

The monitor reports itself with `POST /v1/ingest/heartbeat` (`component: "monitor"`).

## Rules every part follows

- **Pacing everywhere.** Every call to someone else's service stays inside that service's limits.
  Calls are spread out with random jitter, never sent in bursts, and errors back off exponentially;
  a 429 or a "slow down" waits at least as long as the service says. Downloads from Instagram are
  jittered too. Each part documents its limits in its README.

- **Nothing is lost.** Stories vanish from Instagram after 24 hours unless they are in a highlight,
  so the collector runs at least hourly, and media is re-hosted on `media.empire.earth` before it
  expires. Instagram's CDN URLs are never stored as `url`.
- **Reposts:** when the account shares someone's reel or post (in a story or as a post), both the
  sharing item and the original (`repost_of`, with media re-hosted) are kept. The original is
  credited to its author everywhere it is shown.
- **The X poster** posts every item oldest first, spread out within the API's limits, through the
  official X API only. Each post carries:
  - the caption;
  - the original date;
  - the highlight names;
  - the categories as hashtags;
  - the media.

  A repost goes up with the original's video, credited to its author ("Reel by @author" and the
  source link). State lives in the backend's database, so nothing is posted twice.
- **The Facebook poster** posts the same content, oldest first, to the owner's own Facebook profile
  with a headless browser on the box. It loads the session as a Playwright `storageState` from the
  secret `earth-empire/facebook-session` (cookies and localStorage, captured where the owner logged
  in). When that session is logged out, the poster stops, logs it, saves a screenshot and waits for
  the secret to be refreshed. It never logs in by itself. Posting is paced gently, with a daily cap.
- Media URLs: the collector may send any `url` the API's `media-url` returned. The API stores the
  key and serves URLs under the current media host, so they move to `media.empire.earth` once its
  certificate is issued.
- Log what happens - every run, every request that failed, and why - and diagnose from the logs.
