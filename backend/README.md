# Earth Empire backend

AWS infrastructure, the database, the API at `https://api.empire.earth`, analysis with Claude,
the X and Facebook posters, and deploys (the site's hosting too). See [CONTRACT.md](../CONTRACT.md).

```
backend/
  ee/                Python package (FastAPI API, worker, CLI `ee`)
    api.py           public read API, ingest, admin pipeline view
    store.py, db.py  SQLite store, pipeline steps, search (FTS5), tags
    analysis.py      frames + transcript + context -> Claude (structured output) -> analysis,
                     categories, summary, description, tags, video covers
    aicoin.py        the server wallet: mints its own short-lived tokens for the aicoin proxy
    compose.py       what a post says; X threads within 280 weighted characters
    xposter.py       X API v2 (OAuth 1.0a), chunked media upload
    fbposter.py      Facebook through a headless browser with the owner's session
    heard.py         the phrase spoken per video (cached transcripts + highlight titles -> Claude),
                     and each highlight's heard_label
    worker.py        the pipeline lanes: analyze, thumbs, home, importance, heard, facets, rubric,
                     x, facebook, housekeeping (heartbeat, backup, site)
    cli.py           `ee` on the box
  infra/             CloudFormation stack and the scripts around it
  deploy/            the box: bootstrap, installer, deploy over SSM, site build and publish
  tests/             unit tests (standard library only) and fixtures loaded through the real ingest API
```

## What runs where

| | |
|---|---|
| Stack | CloudFormation `earth-empire` (us-east-1), everything tagged `project=earth-empire` |
| DNS | Route 53 zone `empire.earth` (its nameservers are set at the registrar) |
| Certificate | one ACM cert for `empire.earth`, `www`, `media`, `api` (DNS-validated, auto-renewing) |
| Site | bucket `earth-empire-site` → CloudFront → `empire.earth`; `www` redirects to the apex |
| Media | bucket `earth-empire-media` (private, versioned, OAC) → CloudFront → `media.empire.earth` |
| API | CloudFront → `api.empire.earth` → the box, port 80 open to CloudFront's addresses only → nginx → uvicorn `127.0.0.1:8000` |
| Box | EC2 `t4g.medium` tagged `Name=earth-empire` (Ubuntu 24.04 arm64, 30 GB gp3, 4 GB swap, Elastic IP), role `earth-empire-box`, SSM only (no SSH port) |
| Backups | bucket `earth-empire-backups`: every part's SQLite state hourly at `state/latest/<part>/…`, daily at `state/daily/<date>/…` (35 days); `facebook/*.png` proofs |
| Logs | CloudWatch Logs `/earth-empire` (90 days), streams `api-*`, `worker-*`, `cli-*`; deploy output too |
| Metrics | namespace `EarthEmpire`: `Heartbeat`, `CollectorRunsOk`, `CollectorRunsFailed`, `WorkerErrors`, `AnalysisCoins`, `XPosts`, `FacebookPosts` |
| Alarms → SNS `earth-empire-alerts` | no successful collector run for 3 h; 3+ failed runs in 2 h; API/worker heartbeat stopped; 5+ worker errors in an hour; EC2 host failure (auto-recover) |

Subscribe to the alerts (once; confirm the e-mail):
`aws sns subscribe --protocol email --notification-endpoint <you@example.com> --topic-arn "$(aws cloudformation describe-stacks --stack-name earth-empire --query "Stacks[0].Outputs[?OutputKey=='AlertsTopic'].OutputValue" --output text)"`

## Deploying

```sh
backend/infra/deploy.sh                    # the stack (keeps the certificate parameter)
backend/deploy/deploy-box.sh backend       # pull main on the box, bootstrap, backend install, restart
backend/deploy/deploy-box.sh               # ... and every part's <part>/deploy/install.sh
backend/deploy/deploy-site.sh [web/dist]   # sync a local web build to the site bucket, invalidate
backend/deploy/box-run.sh 'ee status'      # any command on the box over SSM
```

The box also rebuilds and publishes the site itself (`deploy/build-site.sh`, from the worker, at
most every 15 minutes) whenever items have gone public since the last build, so new items get
their prerendered share pages. `ee settings site.auto_build 0` turns that off.

Domains were attached with `infra/request-cert.sh` + `infra/finish-domains.sh` (both idempotent;
re-run them if the stack is ever rebuilt).

Shell on the box: `aws ssm start-session --target $ID`, then `sudo -i`, with
`ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=earth-empire Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)`.
Resource ids and hostnames: `aws cloudformation describe-stacks --stack-name earth-empire --query 'Stacks[0].Outputs'`.

## Thumbnails and app links

- Every media item that arrives with `thumbnail: null` gets one: about 640 px on the short side, at
  `items/<id>/<n>.thumb.jpg` (`r<n>` for a repost original's media). The worker's `thumbs` lane makes
  them right after ingest and backfilled the existing items. A thumbnail the collector sends wins.
- The site's CloudFront function leaves `/.well-known/*` alone on both hosts. `deploy-site.sh`
  uploads those files as `application/json`. `build-site.sh` builds with
  `SITE_URL=https://empire.earth`, `VITE_API_BASE=https://api.empire.earth` and
  `EE_REPO_ROOT=/opt/earth-empire/repo`, so the apps' association files are included.

## Status, health and the owner's token

- `GET /v1/status` (public) is the apps' status screen. It covers every component (API, database
  and backups, workers, analyzer, collector, monitor and any part that sends heartbeats, X and
  Facebook posters, site build, disk, memory, CPU, queues) with state, last success, last error and
  details. It also lists the current jobs with progress and elapsed time, and the latest 50
  events. Texts are scrubbed (`ee/status.py`), and unpublished items are never named.
- Parts report with `POST /v1/ingest/heartbeat` (ingest token); a silent part shows `down` after
  30 minutes.
- `earth-empire/admin-token` is the owner's token for owner-only endpoints. The apps check it with
  `GET /v1/admin/me` once the owner types it. To read it (owner only):
  `aws secretsmanager get-secret-value --secret-id earth-empire/admin-token --query SecretString --output text`.
  To rotate it, put a new random value in the secret; the API picks it up within 5 minutes.

## Persistence

Every part's SQLite files under `/var/lib/earth-empire/<part>/` are backed up hourly with SQLite's
online backup API to `s3://earth-empire-backups/state/` (`ee/backup.py`). That covers Earth Empire's items,
the pipeline and posting state, settings, the collector's and the monitor's state. The EBS volume
also survives instance termination.

```sh
ee backup                          # now
ee-restore-state --check           # download and verify the latest; change nothing
ee-restore-state [YYYY-MM-DD]      # stop ee-* services and timers, restore (latest or that day), start them
```

A rebuilt box restores the latest state in `deploy/install.sh` before any service starts. Tested
2026-10-25: a restore into a scratch directory matched the live row counts in every table, and an
in-place restore stopped and restarted the API, worker and collector timer cleanly.

## The pipeline (CONTRACT.md "The pipeline")

Each item has a row per step in `steps`: `analyze` → `site` → `x`, `facebook`. States: `pending`,
`running`, `done`/`posted`, `failed` (with the error, retried with exponential backoff from 2
minutes to 4 hours, 8 attempts), `skipped`. Every transition is in `transitions` and in the log as
`pipeline.transition`. Lanes take the oldest due item, so the backlog goes oldest first and a
failure never blocks the next item. An item whose `x` or `facebook` step is `posted` is never
posted again; fixture items (`extra.test`) are never posted.

```sh
ee status                     # counts per step and state, latest failures, 24 h spend
curl -H "Authorization: Bearer $TOKEN" https://api.empire.earth/v1/admin/pipeline
ee estimate                   # what analyzing the pending backlog would cost
ee analyze <id>... | --next N # analyze now (ignores the daily cap)
ee steps retry [step]         # requeue failed steps
ee steps set <id> <step> <state>
ee settings [key [value]]
ee delete <id>... | --tests   # remove items (--tests: the ig_test_* fixtures)
```

## Analysis and cost

Per item, Claude (`claude-sonnet-5-5` through the aicoin proxy, effort `medium`, structured JSON
output) receives every image (1568 px), frames across every video (one per 3 s, 4-16 frames,
768 px, each labelled with its time), the speech transcript (OpenAI `whisper-1` through the proxy,
timed segments), all metadata, the category taxonomy, the nearest 30 analyzed items, people the
owner named before (and how), and recurring places. It returns the contract's `analysis` plus
categories, new categories (at most 2, only when nothing fits), summary, description and the best
cover frame of each video, which is saved at full size as `items/<id>/<n>.cover.jpg`.

People are named only from the post's own signals or a name the owner gave earlier when this
post's text links to it, never by appearance; the fixtures confirmed it (one person named from an
on-screen caption, the others described).

**Measured cost** (7 analyses of the fixtures, 2026-10-25): 7,100 input + 1,060 output tokens per
item on average, **4.9 coins ≈ $0.037 per item** at the proxy's metering, plus **1 coin per video**
for transcription. Photo post ≈ 3 coins, carousel ≈ 4, short video ≈ 7-8 with transcription.
**Backlog of N items ≈ 6 × N coins ≈ $0.055 × N** (1,000 items ≈ 6,000 coins ≈ $55; mostly-video
accounts toward the upper end, long videos a little more since frames are capped at 16).

**Pacing:** 5-20 s of random pause between analyses. Proxy 429s and 5xx responses retry with growing
waits; an empty wallet waits an hour.

**Cost guard:** the worker analyzes at most `analysis.daily_cap` items a day (default **20**).
To work through an approved backlog: `ee settings analysis.daily_cap 1000`. `ee estimate` shows
what is pending.

### Heard phrases (CONTRACT.md "Heard")

The `heard` lane gives each item with a video the short phrase actually spoken that its highlight
title stands for ("3" -> "у тебе 3"), stored as `items.heard` beside a signature of the
transcripts and highlights it came from (`items.heard_sig`); a changed signature queues the item
again. Each highlight gets `heard_label`/`heard_reason` (the most common phrase among its items);
its Instagram `title` is never touched. It only reads the cached `transcripts` (or, for items
analyzed before those were cached, the analysis's transcript), never transcribes, and runs only
when no analysis is waiting: 8 items per call (`heard.batch_size`), at most `heard.daily_cap` (150)
calls a day, `heard.enabled` to switch it off, `heard.model` to pick a model (empty: the default).
Budget waits as in every AI lane. `ee heard` shows the queue and the labels, `ee heard run` works
through the queue now, `ee heard labels` recomputes the labels. The monitor does the same for its
hits in its own worker (monitor/README.md).

### The server wallet (how the backend pays)

`ee wallet init` (done) generated an Ed25519 key **on the box**; the key exists only in the secret
`earth-empire/claude`. The backend mints itself a one-hour API token from it as needed.

- Address and balance: `ee wallet show` on the box (the address is public by design; the key is not)

**Funding it** (the operator, nobody else): in the aicoin admin app (`~/src/aicoin/ios-admin`),
Wallets → this address → Credit; or

```sh
curl -X POST https://proxy.aicoin.oeaio.com/admin/credit -H "X-Admin-Token: $AICOIN_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"address":"<the wallet address>","amount":6000,
       "reason":"earth-empire analysis","reference":"earth-empire-2026-10-a"}'
```

(`reference` makes a repeat harmless; at most 1,000,000 per call.) Optionally exempt the wallet
from the IAP spend budget so Earth Empire's analyses don't use up what apps may sell:
`aicoin-proxy/scripts/set-budget.sh --internal <the wallet address>`. With an empty wallet, analysis
waits (`analysis.out_of_coins` in the log) and resumes by itself once credited.

## The X poster

Official X API v2 only: `POST /2/tweets`, `POST /2/media/upload/{initialize,<id>/append,<id>/finalize}`
(4 MB chunks), `GET /2/media/upload?command=STATUS`. OAuth 1.0a user context from
`earth-empire/x` (`api_key`, `api_secret`, `access_token`, `access_secret`). Each item is a thread: first tweet = type and date, highlight names, repost credit
("Reel by @author <source link>"), then the description, the original caption in quotes, and the
category hashtags, packed by sentence; " (n/m)" on each. A video goes alone (transcoded to H.264
≤1280 px, trimmed to 2:20, X's limit without Premium); images four per tweet; extra media go in
replies. A repost carries the original's video. Every tweet id is saved as it is created, so a
retry continues the thread.

**Limits and price** (docs.x.com, 2026-10): `POST /2/tweets` 100 per 15 min per user, 10,000 per
24 h per app; media upload 1,875 per 15 min per user. X is pay-per-use: **$0.015 per post, $0.20
per post containing a URL** (so a repost's credited first tweet costs $0.20), user reads $0.010.
An item is ~2-3 tweets ≈ **$0.03-0.05**, a repost ≈ $0.23. 1,000 items with 10% reposts ≈ $55.

Pacing: one item every `x.interval_minutes` (30, with -20%/+30% random jitter), at most `x.daily_cap` (40) a day, both settings.
A 429 pauses until X's reset; **a billing refusal** (HTTP 402, or 403/429 mentioning credits,
payment or a usage cap) **pauses posting** (`x.paused_until`), logs `x.no_credits`, and leaves the
item pending, with no retries. After buying credits: `ee settings x.paused_until ''`.

```sh
ee x dry-run --n 5            # print the next threads, post nothing
ee x post <id>                # one item, now
ee settings x.dry_run 0 && ee settings x.enabled 1    # go live (the worker then posts)
```

## The Facebook poster

The owner's own profile, through headless Chromium on the box with the owner's session (Facebook
has no API for profiles; this is against Facebook's automation terms, at the owner's risk to their
own account). The session is a Playwright `storageState` in `earth-empire/facebook-session`.

- **Never logs in.** Logged out or a checkpoint: it stops, saves a screenshot, logs
  `facebook.needs_owner`, and waits until the secret changes, then resumes by itself.
- **Never answers Facebook's own questions** about the account. A settings prompt (such as
  "Review audience": who sees future posts and reels) stops the run with a screenshot,
  `facebook.owner_decision` in the log, and a 12-hour pause. The owner completes it once by hand.
  As of 2026-10-25 this prompt is pending: open facebook.com, start a post, add a photo and finish
  "Review audience". The composer's audience is the account's default (check whether it is Friends or Public).
- **Pace:** at most `facebook.daily_cap` (4) posts a day, random gaps between
  `facebook.min_gap_minutes` (120) and `max_gap_minutes` (300), only within `facebook.active_hours`
  (9-22) in `facebook.timezone` (Europe/Kyiv). A warning ("posting too fast", "temporarily
  blocked", "try again later") pauses it for 72 hours.
- **Proof:** a screenshot after every post (box: `/var/lib/earth-empire/backend/facebook/`, and
  `s3://earth-empire-backups/facebook/`), and the post's URL read from the profile when possible.
  If the composer fails after Post was clicked, the step fails permanently with "check the profile",
  so nothing is posted twice.
- **Backdating:** profile posts have no reliable "backdate" option in the composer (Pages do), so the
  original date goes in the text. Verify in the composer once the audience prompt is done.

```sh
ee facebook check             # is the session logged in? (screenshot)
ee facebook dry-run [--id X]  # fill the composer (media, text), screenshot, close without posting
ee settings facebook.dry_run 0 && ee settings facebook.enabled 1    # go live
```

Refreshing the session: capture a Playwright `storageState` where the owner is logged in, then
`aws secretsmanager put-secret-value --secret-id earth-empire/facebook-session --secret-string file://state.json`.

### Remote view (fallback for a human login on the box)

`ee-remote-view` runs Xvfb `:99`, x11vnc and noVNC on `127.0.0.1:6080` only (CONTRACT.md "The box").

```sh
# 1. on the box
aws ssm start-session --target $ID
sudo systemctl start ee-remote-view
sudo -u earth ee-browser-login facebook https://www.facebook.com/     # or instagram
# 2. on the Mac, in another terminal
aws ssm start-session --target $ID --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=6080,localPortNumber=6080
# 3. open http://localhost:6080/vnc.html, Connect, log in by hand, close the browser window
# 4. sudo systemctl stop ee-remote-view
```

That profile lives in `/var/lib/earth-empire/browser/<name>/`. The Facebook poster itself uses the
`storageState` secret, not this profile.

## Secrets (values never in git)

| Secret | Holds | Set by |
|---|---|---|
| `earth-empire/ingest-token` | random string, the collector's bearer token | generated by `infra/create-secrets.sh` |
| `earth-empire/instagram` | `{"username","password","totp_secret"?}` of the downloader account | owner |
| `earth-empire/target` | `{"username"}` of the owner's account Earth Empire publishes | owner |
| `earth-empire/x` | `{"api_key","api_secret","access_token","access_secret"}` | owner |
| `earth-empire/facebook-session` | Playwright storageState JSON | owner |
| `earth-empire/claude` | `{"proxy_url","model","wallet_address","wallet_private_key"}` | `ee wallet init` on the box |

```sh
aws secretsmanager put-secret-value --secret-id earth-empire/instagram \
  --secret-string '{"username":"<downloader login>","password":"<password>","totp_secret":"<base32, optional>"}'
aws secretsmanager put-secret-value --secret-id earth-empire/target --secret-string '{"username":"<owner's account>"}'
aws secretsmanager put-secret-value --secret-id earth-empire/x \
  --secret-string '{"api_key":"…","api_secret":"…","access_token":"…","access_secret":"…"}'
```

## Monthly cost (us-east-1, on-demand)

| | $/month |
|---|---|
| EC2 t4g.medium (730 h × $0.0336) | 24.53 |
| EBS 30 GB gp3 | 2.40 |
| Public IPv4 (Elastic IP) | 3.65 |
| Route 53 zone + queries | 0.60 |
| Secrets Manager, 7 secrets × $0.40 | 2.80 |
| CloudWatch: 7 custom metrics, 5 alarms, logs | ~3 |
| S3 (media ~20 GB, versions, backups, site) | ~0.60 |
| CloudFront (within the always-free 1 TB / 10 M requests) | 0 |
| **AWS total** | **≈ $38** |

Plus usage: Claude via aicoin ≈ $0.055 per analyzed item, X ≈ $0.04 per posted item. `t4g`
unlimited mode bills $0.04 per vCPU-hour of sustained CPU above the 20% baseline (ffmpeg, Chromium
bursts are short). A 1-year Savings Plan would cut EC2 by ~35%.

## Testing

```sh
python3 -m unittest discover -s backend/tests                 # store, pipeline, composition (no deps)
backend/deploy/box-run.sh 'set -a; . /etc/earth-empire/env; set +a; cd /opt/earth-empire/repo/backend && sudo -E -u earth /opt/earth-empire/backend-venv/bin/python tests/load_fixtures.py'
```

The fixtures (`ig_test_*`, Wikimedia Commons media) go through the real ingest flow: presigned
upload, items, highlights, profile and a run. `ee delete --tests` removes them.
