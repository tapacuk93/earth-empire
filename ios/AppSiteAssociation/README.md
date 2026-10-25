# Universal Links for empire.earth

`apple-app-site-association` is for the backend (which deploys the site's hosting) to serve at

    https://empire.earth/.well-known/apple-app-site-association
    https://www.empire.earth/.well-known/apple-app-site-association

as `Content-Type: application/json`, over HTTPS with no redirect, at the same paths on both hosts.

It opens the app at the site's own routes (`web/src/main.tsx`): `/`, `/item/<id>`,
`/category/<slug>`, `/highlight/<id>?item=<id>`, plus the home grid's `?q=`, `?kind=` and
`?category=`. `HTS38ZPRVH` is the team id the app is signed with (it is public in every such
file). The app's entitlement lists `applinks:empire.earth` and `applinks:www.empire.earth`.
Apple's CDN fetches the file when the app is installed, so it must be live before the
app is.
