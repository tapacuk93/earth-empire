# Earth Empire — contract between the parts

**Earth Empire** is the project. It takes the owner's Instagram account (posts, reels, stories,
highlights), describes and sorts every item with Claude, and publishes it at
**https://empire.earth**, in the Earth Empire apps (iOS and Android), and on the owner's X and
Facebook. It also watches public videos elsewhere for moments that concern the owner. The collector,
backend, monitor, site, apps and posters are its parts.

One public repository, github.com/tapacuk93/earth-empire - so no secret, password, token or
account detail is ever committed; they live in AWS Secrets Manager.

| Folder | Owns |
|---|---|
| `backend/` | AWS infra, the database, the API at `api.empire.earth`, analysis and categories with Claude, the X poster, deploys (including the site's hosting) |
| `collector/` | the headless browser in AWS that reads the account and feeds the API |
| `web/` | the site at `empire.earth` - a static app over the API, every browser and screen size |
| `ios/` | the iOS app Earth Empire (`com.oeaio.earthempire`) over the API |
| `android/` | the Android app Earth Empire over the API |
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
  - `earth-empire/telegram`: `{"api_id", "api_hash"}`; `earth-empire/telegram-session`: `{"session", "user_id"}`,
    a Telethon session string the owner makes once with `monitor/deploy/telegram-login.py` (the monitor reads
    public channels with it, nothing else).
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
  "importance": 0.6 | null,                // set by the backend: 0-1, how significant the content is;
                                           // judged on content only, never lower for a story or a repost
  "detection": null | {                    // set by the monitor's scan of the item; context only
    "matched": true,                       // any hit, low confidence too
    "hits": [{"kind": "name" | "language", "phrase": "тарас" | null, "lang": "uk" | null,
              "media": 0, "at": 12.4,      // media index and seconds into it: TikTok mode starts here
              "confidence": 0.62, "excerpt": "…", "translation": "…" | null}],
    "model": "…", "scanned_at": "…"
  },
  "placement": 1 | 0.5 | 0.25 | 0.125 | null, "placement_reason": "…" | null,  // set by the backend: where the
                                           // item lives (see "Home layout"); also as curation/curation_reason
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
  "priority": "new" | absent,              // set by the collector: appeared on Instagram after the
                                           // backfill began (a new post, story, repost, or a story
                                           // added to a highlight); see "The pipeline"
  "collected_at": "…", "updated_at": "…",
  "published_at": "…",                     // set by the backend when the item went public (see "The pipeline")
  "heard": null | {                        // set by the backend: the short phrase spoken in the item's video
    "text": "у тебе 3",                    // that a highlight title stands for (see "Heard"); null until
    "highlight_id": "hl_…" | null,         // worked out, or when nothing in the speech matches
    "media": 0 | null, "start": 2.1 | null, "end": 3.4 | null,   // media index and seconds into it
    "confidence": 0.9, "model": "…", "at": "…"
  }
}

// Highlight
{"id": "hl_<pk>", "title": "Travel", "cover": "https://media.empire.earth/highlights/<id>/cover.jpg",
 "item_ids": ["ig_…"], "updated_at": "…",   // item_ids in the highlight's own order
 "heard_label": "у тебе 3" | null,          // set by the backend: the fuller phrase the title stands for,
 "heard_reason": "heard in 3 of its 4 videos with speech; …" | null}   // and why; `title` stays Instagram's

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
  `{"upload_url": "<presigned PUT>", "public_url": "https://media.empire.earth/…", "headers":
  {"Content-Type": "video/mp4"}, "exists": bool}`. PUT the bytes to `upload_url` with exactly the
  `Content-Type` that was asked for (it is signed); `exists` says the key is already there.
- `PUT /v1/ingest/items` `{"items": [Item without categories/summary]}`: an upsert by id. An item
  may carry `"priority": "new"` (it just appeared on the profile) or `"backfill"`; without it, an
  item taken in the last 3 days counts as new. **New items go first in every step** (analysis,
  thumbnails, layout, site, X, Facebook): new ones newest first, then the backlog oldest first. A new
  arrival goes next at the following step boundary. Re-scoring for a new importance rubric comes
  last of all. A
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
- `GET /v1/admin/settings` → `{"size": {"half_life_days", "age_floor", "importance_w", "display_exponent"}, "placement": {"post",
  "dedicated", "shared", "repost", "story", "hit_top", "hit_bottom"}, "rubric": {"version", "text", "reason",
  "by", "history": [{"version", "text", "reason", "by": "backend|claude|owner", "applied", "created_at"}]},
  "rubric_review": bool, "formula"}`; `PUT` the same shape, any part (rubric: `{"text", "reason"?}`),
  → the new settings. A new rubric text becomes the next version and items are re-scored.
- `DELETE /v1/admin/items/{id}` → `{"ok", "id", "media_objects_removed"}`: removes an archive item for
  good (its data, pipeline state, and every version of its media under `items/<id>/`), and the site
  is rebuilt without it.
- `GET /v1/admin/pipeline` (the ingest token works here too), `GET /v1/admin/items/{id}`
  (the item whatever its state, with its steps and transitions), `POST /v1/admin/items/{id}/reanalyze`.

## Detection

**Everything in the account's own profile is public:** every mirrored item (posts, reposts,
stories, highlight stories) once it is analyzed, scanned or not, matched or not. The only exception
is an image-only repost (see "The pipeline"). Videos the monitor finds elsewhere are public only when
the owner publishes them ("+", `POST /v1/monitor/hits/{id}/publish`).

The monitor also scans archive items with its detectors (the owner's phrases, out-of-place Ukrainian
or Russian) and reports the result as context:

- `PUT /v1/ingest/detections` (ingest token)
  `{"detections": [{"id": "ig_…", "detection": {"matched": bool, "hits": [Hit…], "model"?, "scanned_at"?}}]}`
  → `{"ok", "published": [], "unpublished": [], "unchanged": n, "unknown": [ids]}`. Send it again
  whenever a rescan changes the result.
- An item with hits carries them as `detection`, so the site shows the chip and the full-screen mode
  starts the video at the first matched moment (`hits[0].media`, `hits[0].at`). Without hits it
  plays from the start.

## AI calls

Every AI call of the backend and the monitor goes through the aicoin proxy, paid by Earth Empire's
server wallet (`earth-empire/claude`) and identified by the header **`X-AICoin-App: earth-empire`**.
The proxy holds Earth Empire to a per-app daily cap of $20.

- **Order:** Claude first. If Claude's side fails (its account is out of credit, it is overloaded,
  5xx), the call goes to Gemini (`gemini-3.5-flash`), then OpenAI (`gpt-5`), through the same proxy and
  wallet, with the same images, frames and JSON schema. The proxy's `/text` carries no images, so the
  provider-native routes are used. Each result records its provider (`analysis.provider`,
  `analysis.model`).
- **Budgets never fail an item.** The proxy's app cap (429 `app_daily_cap_reached`, `reset_at`), an
  empty wallet (402), a provider's credit ("credit balance too low"), and Earth Empire's own limits
  (`ai.daily_budget_usd` $20, the daily caps on analyses, re-scores and facet runs) keep the item
  queued as it is. The lane waits until `reset_at` when there is one, otherwise backs off 1, 2, 4 …
  minutes up to 15 with jitter, and retries with no limit. New items stay first. `GET /v1/status`
  shows it on the `ai` component ("waiting for budget: app cap, resets 00:00 UTC", "wallet empty",
  "provider credit", and `next_retry`). Other errors keep their normal limited retries.

## Heard

The owner names Instagram highlights after a phrase said in their videos, often abbreviated ("3" for
"у тебе 3", "в Тараса 3"). The backend works out the phrase actually spoken, so the site and apps can
label a video (and a highlight) with it; the Instagram `title` is never changed.

- **Per item** with a video (items in highlights first): Claude reads the item's cached speech
  transcripts (timed segments; nothing is transcribed again, items analyzed before transcripts were
  cached use the analysis's own transcript, without times) and its highlight titles, and answers with
  the short phrase as spoken - a few words, in the original language and spelling - that a title
  stands for, its media and start/end, and a confidence. Nothing matching: null; nothing is invented.
  For an item in no highlight the reference is the post's own description (the caption's first line
  without hashtags or mentions, else the first sentence of its description): the words actually spoken
  that say it, with where they sound, `highlight_id` null; null when it is not spoken. Stored as Item
  `heard`. The clients label such a card with that description until then.
- **The monitor's phrases come first:** every batch carries the phrases the monitor listens for (with
  a few variants). In any item, highlight or not, a moment where one is spoken - as written, a variant,
  misheard, or in wording Claude judges similar or related - is the label, made fuller as actually
  spoken around it; it wins over a highlight title or a description. The phrase list is part of each
  item's signature, so editing the phrases works every video out again.
- **The owner's label:** `PUT /v1/admin/items/{id}/heard {"text": "у тебе 3"}` (owner) sets an item's
  label, `by: "owner"`, confidence 1; the job never changes it, and it counts for its highlight's
  `heard_label`. `""` or `null` hands it back to the job. → `{"id", "heard"}`. The apps and the site make
  a card's label (and the fullscreen gold label) editable in place for the owner: a tap edits it,
  leaving it saves.
- **Per highlight:** `heard_label` is the phrase most of its items say (ties: the surer one, spelled
  as in its surest item; confidence below 0.3 does not count), with `heard_reason`; null when none of
  its videos says one.
- **Continuous:** the worker's `heard` lane, alongside analysis (every job runs in parallel), takes items with
  speech whose phrase was never worked out, or was worked out from other transcripts or other
  highlights (membership or title changed), several items (`heard.batch_size`, 8) per call, at most
  `heard.daily_cap` (150) calls a day, within the AI budget (waits like every AI lane, see "AI calls").
  An item answered badly twice is left without a phrase until its transcript or highlights change.
  `GET /v1/status` shows it as the `heard` component (queue, done, heard, highlights labelled, calls
  today, last run). By hand: `ee heard [show|run|labels]`.
- **Monitor hits** carry `heard` too (see "Monitor"): the short phrase spoken around the match.

## Facets

The groupings the site and apps browse by (places, themes, people, projects, …) are not fixed.
Claude defines them from the public content and redefines them as it changes:

- **When:** whenever something changed, spaced so that `facets.daily_cap` runs (12 by default, the
  cost guard) cover the whole day - at most one every 2 hours - paid from the server's aicoin wallet.
  Between runs every newly published video and found clip joins, per facet, the category whose
  members it is most like (embeddings, no AI), so it shows in its category at once.
- **Improving:** each run Claude writes notes to itself (what it changed and why, what to watch, ideas
  to try); the next run reads them with how the categories fared since (sizes, how many joined by
  similarity, how many fit nowhere). Notes are kept in `facet_notes`; `ee facets show` prints them.
- **Order on Home:** a video's rank is freshness × level - its level's weight (L1 1, L2 ½, L3 ¼, L4 ⅛)
  halved every 30 days since it arrived (a found clip: since it was published). Inside a category
  the highest rank leads; categories go by their best video's rank, so today's videos and their
  categories rise to the top.
- **From what:** a compact summary of the public items only (date, summary, keywords, place,
  categories) and the current facets. Nothing about visitors is collected or used.
- **Stability:** existing facet and category ids and names are kept unless they no longer fit, so the
  site does not reshuffle. Past 400 items, the newest 400 go to Claude, and the rest join the category
  they are most similar to (embeddings).

Public:

- `GET /v1/facets` → `{"facets": [{"id", "name", "description", "categories": [{"id", "name",
  "description", "count", "item_ids": ["ig_…"]}]}], "generated_at"}`: only public items; categories
  by count. An item can be in several categories.
- `GET /v1/items?facet=<facet id>:<category id>` → that category's items, newest first.
- `GET /v1/tags/graph` puts the facets' categories at `level` 0 (`kinds: ["facet"]`, with `facet`,
  `facet_name`, `category`), linked to the tags their items share most. The tags follow at levels 1+.

These replace hard-coded places and categories on the site and in the apps. The per-item
`categories` from the analysis stay as tags.

## Home layout

Home is two zoomable mosaics and a tag graph below them. Everything here is built from published
items and published monitor hits only.

- **One panel.** Every published item, and every AI-found hit the owner approved with "+", is in a
  single mosaic.
- **Closeness** is similarity. The backend embeds each item's description and analysis (and each
  hit's excerpt) with an open-source multilingual sentence model on the box. It places everything
  with one seeded t-SNE, and puts a new tile next to its nearest neighbours without moving the others.
  When the mosaic has doubled, it is placed again, aligned to the old picture.
- **Size: four levels.** A tile's size is its level's weight; age and importance no longer change it
  (their settings remain, marked unused for size). Tile area follows `size ** display_exponent`
  (default 2), and `/v1/layout` sends `display_exponent`.

  | Level | Weight | Profile items (from placement) | AI-found items (monitor hits) |
  |---|---|---|---|
  | **L1** | 1 | a post, or an item in a **dedicated** highlight | Claude rates the hit's significance (the importance rubric plus the detection confidence) and picks the level, with a short `level_reason`. The owner may override it on the Detected screen. A hit appears only once approved with "+", at its level. |
  | **L2** | 0.5 | an item in a **shared** (large) highlight | |
  | **L3** | 0.25 | a repost (Instagram's Repost feature) | |
  | **L4** | 0.125 | a story in no highlight | |

  The weights are the placement settings (`placement.dedicated`/`post`, `shared`, `repost`, `story`).
  Items carry `placement` and `placement_reason` (also as `curation`/`curation_reason`). Importance
  still sets AI-found levels and breaks ties in ordering. Time orders stay by `taken_at`.
- **Importance is scored from the item itself:** the images, frames across every video, the speech
  transcripts (for a repost, the original's audio too), the on-screen text and the description, with
  the current rubric. Transcripts are cached, so re-scoring never transcribes twice.
- **The importance rubric** is plain text in settings, with every version kept. Once a day, Claude
  reviews it against the content and proposes a better one. A refinement (same intent, clearer or
  more accurate) is applied as a new version, and any other proposal is recorded but not applied.
  The owner can also replace it. A new version re-scores every item in the background, within
  `importance.rescore_daily_cap` (400) a day.
- **Background jobs** run continuously and all at the same time, several items each: analysis in
  `analysis.lanes` (3) parallel lanes, each claiming its own item (new items first, then the owner's own,
  then reposts), importance `importance.batch` (3) a turn, heard several videos a call. They share the
  day's budget, whose last `ai.own_reserve_usd` only the owner's own items use. The jobs: importance
  scoring, the heard phrases (see "Heard"), the daily rubric review, facets, and the layout (every
  minute). `GET /v1/status` (owner) shows each one as a component (`importance`, `heard`, `rubric`,
  `facets`, `layout`, `spend`) with its queue,
  progress, the rubric version, the last facets run, the last layout recompute and today's spend
  by purpose. The item being worked on now is in `activity.jobs`.

Public:

- `GET /v1/layout` → `{"tiles": [Tile], "updated_at", "display_exponent", "size_params"}`, newest first, where
  `Tile = {"id", "kind": "item" | "hit", "source": "profile" | "ai_found", "level": 1-4, "x": 0-1, "y": 0-1,
  "size": 1 | 0.5 | 0.25 | 0.125, "placement", "placement_reason", "importance", "label", "taken_at",
  "attached_to"?: "<video id>"}`. A hit's `id` is its hit id (details in `/v1/published`). **Images are
  never tiles of their own:** an item without video carries `attached_to`, its most similar video, sits
  right beside it at 0.45 of its size, and takes its own level. Items with a video are laid out by
  similarity.
  `halves` (`{"top": [], "bottom": tiles}`) is still sent for one release, for older clients.
- `GET /v1/items/{id}/related?limit=20` → `{"related": [{"id", "kind", "score", "rank", "curation",
  "item"?: Item}]}`, ranked across everything: `score` is the similarity, and `rank` = score ×
  (0.5 + 0.5 × placement) orders the list. Equal ranks go to the newer item, and an image follows
  its video. Also takes a hit id.
- `GET /v1/items/{id}/explain?lang=uk-UA` → `{"lang": "uk", "mode": "caption" | "analysis", "text", "model",
  "cached"}`: the "?" of the fullscreen viewer, what is happening, in the viewer's language (the browser's or
  device's, primary subtag). A post (post, carousel or reel, not a repost) with a caption is explained by
  its own description, translated faithfully; anything else by Claude from its analysis (who, what, where,
  what is said), two to four sentences. One answer per item, language and source text, kept; new ones are
  capped per day (`explain.daily_cap`, 300), and past it the answer is 503: the clients then show the
  English description. 400 for a `lang` that is not a language tag.
- `GET /v1/tags/graph?max_nodes=300` → `{"nodes": [{"tag", "kinds": ["keyword", …], "count", "level"}],
  "edges": [{"a", "b", "count", "weight"}]}`. `level` 0 holds the 12 broadest tags (by count), 1 the
  next 36, 2 the next 96, then 3, so zooming in reveals deeper levels. Edges are co-occurrence on the
  same item (`weight` = count / sqrt(count_a × count_b)), at most 6 strong edges per tag.
- `GET /v1/items?tag=` lists a tag's items (newest first), for its full-screen mode.

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

Every item goes through these steps in order. **New items come first:** the collector ingests
items marked `"priority": "new"` before any backfill item, and the backend analyzes them ahead of
the backlog, newest first. The backlog goes oldest first, and each new item goes through as it
arrives. Each step has its own recorded state, and a failure retries with
backoff without blocking other items. Every transition is logged.

1. **Downloaded:** the collector has ingested it (a post, carousel, reel, story, highlight story, or
   a repost together with its original).
2. **Analyzed:** the backend has written `analysis`, `categories`, `summary` and `description`.
   **Mirroring the account is never missed:** the account's own posts and stories (no `repost_of`)
   are public in the API, the site and the apps as soon as they are downloaded, with their own caption;
   analysis fills in the rest when the budget allows (the day's last `ai.own_reserve_usd` is only for
   it, every other job stops there). A repost is public only from this point on (a monitor detection
   is not required, see "Detection"), and never an **image-only repost**: an item
   with `repost_of` and no video, in its own media or the original's (someone else's photo, shared
   in a post or a story). Such an item is kept and analyzed, but its `site`, `x` and `facebook`
   steps are `skipped`. The X and Facebook posters take only analyzed items. It never appears in `/v1/items`, `/v1/layout`, related lists, the tag graph
   or the site. A repost of a video is public as usual, and so is every photo the account posted
   itself. `published_at` is when that happened.
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
Instagram reposts and their authors), `recommended` (what a platform suggests next to a seed;
`via` names the seed: a hit id or a backend item id, at most `rec.max_hops` hops away) and `mirror`
(the owner's own video posts, scanned as ground truth; left out of `/v1/monitor/hits` unless
`source_kind=mirror` is asked for). The monitor makes no Instagram requests of its own: its Instagram
data is what the collector ingested into the backend. The monitor only watches: it never likes, follows, comments or
messages on any platform.

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
  "platform": "telegram" | "youtube" | "facebook" | "instagram" | "tiktok" | "x" | "web",
  "source_kind": "official" | "followed" | "reposted_author" | "reposted" | "recommended" | "mirror",
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
  "published_at": "…" | null,               // set by the owner's publish
  "level": 1 | 2 | 3 | 4 | null,           // Home level (L1 biggest), chosen by Claude from the importance
  "level_reason": "…" | null,              // rubric and the detection confidence; the owner may override it
  "ai_level": 1 | 2 | 3 | 4 | null,        // Claude's level; null until judged
  "level_by": "ai" | "owner",               // whether `level` is Claude's or the owner's override
  "heard": null | {"text": "у Тараса троє", // the short phrase spoken around the match, as spoken (few words,
    "start": 12.2 | null, "end": 13.1 | null, // original language), from the stored transcript; null until
    "confidence": 0.8, "model": "…", "at": "…"}   // worked out or when no clear phrase is spoken
}
```

**Only the apps' Home screen is public.** Detected (hits), Status and Settings are the owner's.

Public (CORS open):

- `GET /v1/published?before=&limit=` → `{"hits": [Hit], "next"}`: the hits the owner approved ("+"),
  newest first, each with its `level`, for the apps' Home screen. Their `clip`/`frame` are public URLs under `media.empire.earth/monitor/public/`.
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
  "claude_variants": ["…"], "updated_at"}], "suggested": [{"text", "why", "sounds": {"uk", "ru", "en"},
  "source": "highlights", "state": "suggested", "created_at"}]}` - `suggested` are phrases Claude
  proposes from tapacuk93's highlight titles; nothing is listened for until the owner accepts it:
  `POST /v1/monitor/phrases/suggested/{text}/accept` | `/reject` → as GET.
  `POST /v1/monitor/phrases/suggest` asks again now (it also runs when the highlights change).
- `GET /v1/monitor/videos?state=&platform=&limit=` → recent videos and their scan state
  (`new | queued | running | done | failed | blocked | skipped`, with `error`, `languages`, `hits`).
- **Heard on hits:** new hits get `heard` in the same Claude call that translates and levels them
  (one call per video, with the timed words around each hit). Hits found before it existed are
  backfilled from the stored transcripts every 5 minutes, a few videos per call, approved hits first
  and the owner's mirrored videos last, within `claude.daily_usd` while leaving a fifth of it for new
  hits. `GET /v1/monitor/status` carries `heard: {"queue", "done", "heard", "last_run"}`.
- `GET /v1/monitor/status` → queue by platform and state, totals, throughput (`cpu_per_audio`),
  today's usage against the caps, open fetch requests, and `stops` (a platform paused by a
  checkpoint, warning, login or billing refusal, with the reason).
- `POST /v1/monitor/hits/{id}/publish {"level"?: 1-4}`: "+" approves the hit for Home at its AI-chosen
  `level` (or the owner's override); `POST /v1/monitor/hits/{id}/unpublish` takes it off → Hit.
  Publishing twice changes nothing; there are no sections.
- `PUT /v1/monitor/hits/{id}/level {"level": 1-4 | "L1".."L4" | null}` → Hit: the owner's level for a hit,
  approved or not (`null` returns to Claude's). Hits found before levels existed are judged in the
  background, a few videos at a time, within `claude.daily_usd`.
- `PUT /v1/monitor/phrases {"phrases": ["тарас", "тарас маслов", "маслов"], "claude"?: true, "rescan"?: true}`
  → as GET. Replaces the list; variants are generated by rule, Claude adds spellings once per new
  phrase (cached), and stored transcripts are matched again (`rescan`).
- **Highlight names** (`phrases.from_highlights`, on by default): every highlight title the monitor has
  seen - current ones and archived ones that left the profile - is listened for beside the owner's
  phrases, as a phrase with all its variants (lowercase words, `3` as `три`, words under three letters
  dropped: "в Тараса 3" → "тараса три"). `GET /v1/monitor/phrases` adds `"owner_phrases": ["…"]`,
  `"from_highlights": true`, `"highlight_titles": [{"title", "phrase", "items", "current", "first_seen",
  "last_seen"}]`, and each phrase an `"origin": "owner" | "highlight"`. `PUT /v1/monitor/phrases` sets the
  owner's phrases; `PUT /v1/monitor/phrases/settings {"from_highlights": true | false}` → as GET. A changed
  list rescans the stored transcripts.
- `POST /v1/monitor/rescan` → `{"ok", "videos"}`: detection again over every stored transcript.
- `GET /v1/monitor/learning` → misses and improvements (below): `{"checked", "matched", "found_first",
  "recall", "misses_by_cause": {cause: n}, "recall_by_day": [{"day", "matched", "found_first", "recall"}],
  "improvements": [{"at", "cause", "change", "reason", "applied", "detail"}], "misses": [{"at", "video_id",
  "item_id", "kind", "phrase", "cause", "detail"}]}`. `GET /v1/monitor/status` carries the summary in
  `learning`, and the heartbeat's `detail` the counts (`recall_mirror`, `mirror_matched`,
  `mirror_found_first`, `misses`, `improvements`) for the Status screen.

**Misses and improvements.** The mirror of tapacuk93's Instagram is ground truth. Every mirrored video
(the owner's video posts, and the originals of the owner's reposts) is scanned with the same detectors.
When it has a hit, the monitor checks whether it had found that video on its own first (the same
platform id or shortcode, the author and date, or the transcript's fingerprint, on a video reached as
official / followed / recommended - TikTok and Facebook included). If not, it records a miss with
one cause - `source_not_in_registry`, `not_scanned_yet`, `not_reached`, `download_failed`,
`transcription_missed`, `below_threshold`, `variant_missing`, `language_id_wrong` - and applies the safe
fix within bounds (add or raise the source, queue its video, seed recommendations from it, learn the
variant, lower a threshold inside fixed bounds, a bigger Whisper model for up to 5 sources). Anything
beyond the bounds or costly is recorded as a suggestion (`applied: false`) for the owner. Recall is the
share of mirrored matches the monitor found first.
- `POST /v1/monitor/sources {"name", "platform", "handle", "expected_languages"?, "kind"?, "country"?, "channel_id"?}`
  → `{"source_id", "account_id"}`

**Monitor media.** A clip or frame of an unpublished hit must not be reachable by guessing a URL. The
media CDN refuses every path under `/monitor/` except `/monitor/public/` (403, enforced in the
backend's stack). So:

- The monitor stores clips and frames privately in S3 under `monitor/clips/` and `monitor/frames/`.
  In owner responses, an unpublished hit's `clip`/`frame` are presigned S3 GET URLs (at most 1 hour),
  signed with the box's instance role. Nothing else is presigned: `video.url`, `video.thumbnail` and
  `at_url` are the platform's own public URLs.
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
