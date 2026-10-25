# Earth Empire

**Earth Empire** is one project with several parts. It takes the owner's Instagram (posts,
reels, stories and highlights), describes every item with Claude, and publishes it all at
**https://empire.earth**, in the Earth Empire apps for iOS and Android, and on the owner's X and
Facebook. Next to that, it watches public videos elsewhere for the moments that concern the owner.

| Part | What it does |
|---|---|
| [`collector/`](collector) | reads the Instagram profile from a headless browser on the box and hands everything to the backend |
| [`backend/`](backend) | AWS infrastructure, the database and the API at `api.empire.earth`; analysis, tags, the Home layout and facets with Claude; the X and Facebook posters; deploys |
| [`monitor/`](monitor) | finds public videos elsewhere that mention the owner, transcribes them on the box, and lets the owner publish what matters |
| [`web/`](web) | the site at `empire.earth` |
| [`ios/`](ios), [`android/`](android) | the Earth Empire apps |

How the parts fit together is in [CONTRACT.md](CONTRACT.md).

Open source under the [MIT License](LICENSE). It uses only open-source dependencies.
