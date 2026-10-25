# web — the site at empire.earth

A static app (Preact + TypeScript + Vite, about 20 KB of gzipped JS) over the public read API in
[CONTRACT.md](../CONTRACT.md). The build goes to `web/dist`; `backend/deploy/deploy-site.sh` syncs it
to S3 behind CloudFront.

```sh
npm ci
npm run dev                         # Vite dev server, API from VITE_API_BASE (default https://api.empire.earth)
VITE_API_BASE=mock npm run dev      # against the bundled fixture (mock/), no backend needed
npm run build                       # typecheck, vite build, prerender -> dist/
npm run build:mock                  # the same over the fixture (what the tests use)
npm run preview                     # serve dist/ the way CloudFront does (port 4173)
npm test                            # Playwright: chromium, firefox, webkit x 5 viewports
```

## Configuration

| Variable | At | Meaning |
|---|---|---|
| `VITE_API_BASE` | build | API origin. Default `https://api.empire.earth`. Before DNS moves, the backend's CloudFront hostname, e.g. `https://dlmlvr97ak287.cloudfront.net`. `mock` uses `mock/fixture.json`. |
| `SITE_URL` | build (prerender) | Public origin for canonical and Open Graph URLs. Default `https://empire.earth`. |
| `VITE_IOS_APP_ID` | build | Numeric App Store id. With it every page carries `apple-itunes-app` (Safari's Smart App Banner, `app-argument` = the page URL). Unset until the listing exists. |
| `VITE_APP_STORE_URL` | build | App Store link for the banner's fallback (default from `VITE_IOS_APP_ID`). |
| `VITE_PLAY_STORE_URL` | build | Play Store link (default `https://play.google.com/store/apps/details?id=com.oeaio.earthempire`). |

Deploy (from the repository root, with AWS credentials):

```sh
cd web && VITE_API_BASE=https://dlmlvr97ak287.cloudfront.net npm run build && cd ..
backend/deploy/deploy-site.sh
```

## Routes

The site presents Earth Empire as data rather than as a profile.

| URL | Page |
|---|---|
| `/` | **Home**: three full-screen modes, stacked so a swipe down moves to the next, with a tappable indicator. (1) **Mosaic**: two pan-and-zoom canvases (pinch, Ctrl/trackpad-pinch wheel, drag). The upper canvas holds the short highlights and the feed, the lower one the long highlights, each with the detected videos published into it. Tiles are grouped by highlight and labelled, sized by recency × importance, and placed by tag similarity. A tile plays muted on hover or focus, and labels, dates and descriptions appear as you zoom. (2) **Tag graph**: tags as nodes sized by count, edges for co-occurrence; zooming reveals finer tags. (3) **Timeline**: newest at the top, one row per day; zooming moves from years to months to days. Everything is computed in the browser (`src/layout.ts`) until the API serves `/v1/layout`, `/v1/items/{id}/related` and `/v1/tags/graph`. The canvas renderer (`src/components/zoom.ts`, no libraries) loads thumbnails only once tiles are big enough, a few at a time, and plays at most one video. Each canvas has a hidden list of links mirroring it; a focused link shows and centres its tile. |
| `/item/<id>?ctx=<context>` | the **vertical feed**: fullscreen, one item per screen. Swipe, wheel, arrow keys or j/k move through the context the item was opened from (`rel:<half>:<id>`, which is that half by relatedness and then the other half's most related; `section:`, `tag:`, `month:`, `place:`, `cat:`, `person:`, `hl:`, `q:`, `kind:`, or everything; see `src/context.ts`). Videos autoplay muted, and a tap unmutes. An overlay holds the description and a few facts, and **More** expands the caption, details and full analysis (the event timeline seeks the video). The URL follows the item on screen, and Close (or Esc) returns to the same spot. A playback button cycles **autoplay next** (the default; stills move on after 5 s), **repeat** and **stop**, and is remembered per visitor. |
| `/highlight/<id>?item=<id>` | Instagram-style story viewer: tap left/right, hold to pause, swipe sideways for the next highlight, swipe down or Esc to close; arrows, Space, `m` on a keyboard |
| `/category/<slug>` | one category |
| `/detected` (owner) | the monitor's hits by confidence, labelled (likely, possible, low confidence), with the excerpt, clip and frame; **+ Publish** puts one on Home; "Fetch N more" asks the monitor to scan more (`POST /v1/monitor/fetch`) |
| `/status` (owner) | component health (`GET /v1/status`, every 10 s), what is running now, latest events, monitor stats (`GET /v1/monitor/status`) |
| `/settings` | the owner token; for the owner, the phrases (variants read-only, Save, Rescan) |

Home is the only public section. It shows the totals, the month band, then everything newest first, then the two sections: **upper**, the highlights with few items plus the regular posts, and **lower**, the highlights with many items. A highlight with at most the threshold items is upper; the threshold starts at the median and can be set with `VITE_SECTION_THRESHOLD` or `?split=N` (`src/sections.ts`). Videos lead each section's media. The hits the owner published (`GET /v1/published`) appear in the panel of
the section chosen at publish. `?watch=<id>` on Home or Detected opens the **fullscreen mode**: one per screen,
swipe or arrow keys up and down. On Home it plays the published hits (frame and clip), then the
Earth Empire's videos.

**Owner mode**, as in the apps: visitors see only Home. The hidden way in is the final "." of the footer: one tap, a pause, then three quick taps open the admin key prompt. `/settings` also accepts the key, at
`/settings`. There the owner enters the token (`earth-empire/admin-token`). It is checked with
`GET /v1/admin/me` and kept in this browser's `localStorage`. The token is checked again on each
visit, and a rejected one is forgotten. Only then do Detected, Status and Settings appear; their
routes show the sign-in form to anyone else. They are not prerendered, are absent from the sitemap,
are disallowed in `robots.txt`, and carry `noindex`. Every monitor and status request sends the
token. Signed storage URLs in a hit are never shown as links.

**Provisional, until CONTRACT.md defines them** (`src/sections.ts`, `src/live.ts`):
- A highlight is in the dedicated section when the API marks it (`section: "dedicated"`, `kind: "dedicated"` or `dedicated: true`); every other highlight is common.
- A hit's suggestion is read from `suggested_section` (`{section, reason}`), and its section from `section`. Publishing sends `{"section"}`.
- Suggested phrases come from `GET /v1/monitor/phrases/suggestions`. Without that endpoint, the highlight titles are suggested. Rejections go to `POST /v1/monitor/phrases/suggestions/reject` and are also kept locally.

## Sharing: prerendered route shells

Share previews need the tags in the HTML, since crawlers do not run JavaScript. After `vite build`,
`scripts/prerender.mjs` reads the API (or the fixture) and writes one small HTML file per route:
`dist/item/<id>/index.html`, `dist/highlight/<id>/index.html`, `dist/category/<slug>/index.html` and
`dist/index.html`. Each has its own title, description, canonical URL, Open Graph tags (`og:image`
from the cover, `og:video` for videos) and Twitter card, plus a plain-HTML copy of the content for
readers without JavaScript. The app boots from any of them. It also writes `sitemap.xml`,
`robots.txt` and `404.html` (the generic shell).

Items published after the last build still open (see 404 handling) with generic previews until the
next build. So rebuild and deploy the site regularly: the backend can run the build and
`deploy-site.sh` after publishing new items, or hourly. If the API is unreachable at build time, the
build still succeeds with generic shells only.

## CloudFront: what the site distribution must do

`scripts/serve.mjs` implements exactly this, and the tests run against it.

1. **Viewer-request function**: map an extensionless path to the shell in its folder, not to
   `/index.html`:

   ```js
   if (r.uri.endsWith('/')) r.uri += 'index.html';
   else if (r.uri.lastIndexOf('.') < r.uri.lastIndexOf('/') + 1) r.uri += '/index.html';
   ```

2. **Custom error responses**: S3 behind OAC answers 403 for a missing key. Map both **403 and 404 to
   `/404.html` with response code 404** (`ErrorCachingMinTTL` about 10 s). `404.html` is the app
   shell, so a new item that has no shell yet still renders, while unknown paths get a real 404 and
   the app shows "Not found" with `noindex`.

The stack currently rewrites every extensionless path to `/index.html` and maps 403 to
`/index.html`. That keeps every route working, but every page then shares the home page's preview.
The two changes above in `backend/infra/stack.yaml` make per-item previews work.

3. **App links**: `dist/.well-known/apple-app-site-association` (copied at build time from
   `ios/AppSiteAssociation/`) and `dist/.well-known/assetlinks.json` (from `android/`, once it
   exists) must be served as `application/json`, with status 200 and no redirect, on both
   `empire.earth` and `www.empire.earth`. So the viewer-request function leaves `/.well-known/*`
   alone (no rewrite, and no www-to-apex redirect for it), and `deploy-site.sh` uploads those two
   files with `--content-type application/json` (S3 would otherwise guess `binary/octet-stream`
   for the extensionless one). When the build runs from a copy of `web/`, set `EE_REPO_ROOT` to
   the repository so the build finds `ios/` and `android/`.

Caching (set by `deploy-site.sh`): `assets/*` is hashed and immutable, and everything else gets
`max-age=60`.

## Data

- `src/api.ts` holds the client, with an in-memory cache. Items seen in a list open at once.
- Tags: `GET /v1/tags` and `items?tag=`. If the deployed API does not serve them yet, `src/tags.ts`
  computes the same tags from all items in the browser, and the mock always does.
- Covers: `media[].cover` (the backend's chosen best frame) is used when present, otherwise `thumbnail`.
- `mock/fixture.json` is generated by `scripts/make-fixture.mjs` over synthetic media from
  `scripts/make-mock-media.sh` (ffmpeg). Every person and account in it is invented.

## Accessibility and platforms

Semantic landmarks and headings, alt text from the analysis (`alt_text`, else `analysis.what`,
`description` or `summary`), visible focus, skip link, focus moved to the new page's heading on
navigation, live regions for result counts and the story position, real buttons for every control,
`prefers-reduced-motion` and `forced-colors` support, and light and dark themes (auto, or chosen
and remembered). The layout is fluid from 320 px phones to 4K (3 to 6 grid columns, safe-area
insets). Targets: Safari 14+, Chrome/Edge/Samsung Internet 90+, Firefox 90+.

## Rules shared with the apps (iOS and Android follow the same)

- **Everything is fullscreen.** Every screen (mosaic, tag graph, timeline, the TikTok wheel, Detected, Settings, Status, 404) fills the viewport edge to edge (`100dvh`, safe areas respected), with no fixed header, footer, side bar, page margins or framing cards. Settings and Status are scrollable panes.
- **Every control floats**: the mode indicator, zoom, playback mode, close, share, "+", the owner tab switcher and the token prompt are small translucent buttons and chips over the content. They fade after about 3.5 s without input and come back on any tap, move, key or scroll (`src/idle.ts`, class `fui`). The admin gesture's "." is a tiny dot in the bottom-left corner that never hides.
- **The mosaic is packed**: an ordered, squarified treemap per half (`pack()` in `src/layout.ts`). It is ordered along a Hilbert curve through the similarity positions from `/v1/layout`, so related videos are neighbours, and areas follow recency × importance. Covers fill each tile, with 1 px gaps. Zoom never goes below the full view and panning stays inside it, so the screen is always covered. One non-empty half takes the whole screen.
- **No word "feed"**: tiles outside any highlight have no label, and the halves have no visible names (screen readers get "Short highlights" and "Long highlights").
- **Images** (only the owner's own) are never standalone tiles. Each takes a slice of its video's tile (`attached_to`, else its most similar video), and in the wheel it follows that video as a 5-second still.
- **Why it is public**: the wheel starts a video 1.5 s before `detection.hits[0].at`. A floating chip shows the excerpt, the translation and the confidence level (likely, possible or low confidence), and the progress bar is marked at every hit. Mosaic tiles show a small hit-count badge once they are big enough.
- **The mark is the Earth**: `web/public/icon/earth.svg` is the one source for the favicon, touch and manifest icons, the floating name pill, the app banner and the default share image (`og.png`). The apps use the same SVG for their icons. The PNGs are rendered from it.
- **The app banner** never covers a fullscreen view. On Home it shows once, as a toast, after the first interaction.
