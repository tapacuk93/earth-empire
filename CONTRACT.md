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
  - `earth-empire/claude`: how the backend reaches Claude (the aicoin proxy and a server wallet
    token, or an Anthropic key).

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
    "width": 1080, "height": 1920, "duration": 12.3 | null
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
  "collected_at": "…", "updated_at": "…"
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
- `GET /v1/items?kind=&category=&highlight=&q=&before=&limit=` → `{"items": [Item], "next": "<cursor>" | null}`;
  newest first; `q` searches captions, summaries, hashtags, locations, highlight titles.
- `GET /v1/items/{id}` → Item
- `GET /v1/highlights` → `{"highlights": [Highlight]}`, in the profile's order
- `GET /v1/categories` → `{"categories": [Category]}`, by count

Ingest, for the collector only (`Authorization: Bearer <earth-empire/ingest-token>`):

- `POST /v1/ingest/media-url` `{"key": "items/<id>/0.mp4", "content_type": "video/mp4"}` →
  `{"upload_url": "<presigned PUT>", "public_url": "https://media.empire.earth/…"}`
- `PUT /v1/ingest/items` `{"items": [Item without categories/summary]}`: an upsert by id. A
  repeated item updates its fields and keeps its categories unless its caption or media changed.
- `PUT /v1/ingest/highlights` `{"highlights": [Highlight]}`: the upsert.
- `PUT /v1/ingest/profile` Profile
- `POST /v1/ingest/runs` `{"started_at", "finished_at", "ok": bool, "counts": {}, "log_url"?}`:
  one record for each collector run, for health checks.

## Analysis

The backend analyzes every item, both the existing ones and each new one as it arrives (and the
original of a repost too). Claude sees all of the following:

- frames sampled across every video, with their timestamps;
- every image;
- a transcript of the speech;
- the caption, tags, mentions, stickers, location, music, date, highlight names;
- the account's earlier items, for recurring people, places and series.

From these it writes `analysis`, then `categories` and `summary`.

- **Who:** people are named only from what the post itself says - photo tags, mentions,
  caption, speech, on-screen text - or from a name the owner gave to a person in earlier items. A
  face is never identified by its looks. Otherwise the person is described, not named.
- **Re-analysis:** an item is analyzed again when its media or caption changes, or when the owner
  asks.
- **Search:** `q` searches the analysis too.

## Rules every part follows

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
- Log what happens - every run, every request that failed, and why - and diagnose from the logs.
