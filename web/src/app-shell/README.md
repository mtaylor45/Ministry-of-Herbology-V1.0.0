# App shell and PWA — the design system

Owned by the design system. The shell's navigation (`Nav.svelte`) lives in `web/src/lib/ui/`;
the layout file that mounts it is `web/src/routes/+layout.svelte` and is the app's screens'.
What lives here is everything the shell does besides navigate: the service
worker's policy, the offline notice, the motion decisions, and the checks that
prove them.

Offline scope, decided and built: **care instructions and the
current Morning Rounds are cached; maps, charts and photos are not.**

## The service worker

`web/src/service-worker.ts` (bundled and registered by SvelteKit; served at
`/service-worker.js`) does three things, in `fetch` order:

1. **The shell.** Everything Vite built plus the static files worth having —
   the display font, the seal, the icons, the manifest — is precached on
   install under this build's `version` and served cache-first. A new
   deployment is a new cache; the old one is dropped on activation.
2. **Pages.** Morning Rounds and a specimen's register, tending and compendium
   facets are kept as their server-rendered HTML. Network first; the copy is
   served only when the network does not answer, and the shell is told. A page
   that was never opened gets a plain "not saved on this device" page.
3. **API reads.** The GETs those pages are built from are kept under a cache
   named after the API's `contract_version` and `mode` from `/healthz` (and
   `scenario`, once the maintainers serves it), so a round cached in one world is dropped
   the moment the API is another. A copy younger than a minute is served at
   once and refreshed behind it; an older one only when the network does not
   answer.

Three things are **never** cached, and `cache-policy.test.ts` holds each:

- a mutating request — only GET is ever stored;
- any URL under `/calendar/` — the feed token is in it;
- `/healthz` — a stale "ok" would hide a dead API.

The decisions are plain functions in `cache-policy.ts`; the worker only
applies them.

### Why not plain stale-while-revalidate

It was asked for, and the bounded version here is deliberate. A SvelteKit page
does not re-render when a background refresh lands, so serving a day-old round
"while revalidating" is serving a day-old round — and the offline notice would
have to show on every navigation to stay honest. A minute covers the specimen
page's polling and a quick back-and-forth; past that, the network is asked
first.

## The offline notice

`OfflineNotice.svelte` is the strip above the section bar. `connectivity.ts`
feeds it from the browser's `online`/`offline` events and from the worker's
messages (`moh:from-cache`, `moh:page-from-cache`, `moh:fresh`), and names the
age of the copy when the copy carried one. It is rendered by `Nav`, the one
shell component every page already mounts, so the shell says it on every
screen without the layout file changing. If the app's screens would rather mount it from the
layout directly, it moves; nothing else does.

## Motion

`motion.ts` decides _which_ navigations turn a page — only between the facets
of one plant — and `Nav.svelte` marks the document with `data-transition` for
the duration. How it moves lives in `base.css`, on the motion tokens, and
`prefers-reduced-motion` removes it **in the stylesheet**, so the preference
holds before hydration and whatever a script does. The seal's entrance and the
task row's settle follow the same rule: tokens for the timing, the stylesheet
for the switch-off.

## Checking it

```sh
# from the repository root: the API in mock mode
PYTHONPATH=api:. MOH_MOCK_MODE=true .venv/bin/uvicorn app.main:app --port 8000
# in web/
npm run build
MOH_A11Y_CHROMIUM=/opt/pw-browsers/chromium node src/app-shell/offline-check.ts
```

`offline-check.ts` drives Chromium through every promise above and prints
what it saw. It stops the real servers rather than emulating offline, because
Playwright's emulation reaches the page but not the worker's own fetches in
this Chromium — the worker kept getting answers with the page "offline".

## Theme, before the first paint

`web/src/app.html` carries the only script that runs before the stylesheet
applies. It reads `moh-theme` from `localStorage` and writes `data-theme` on
the document element, so the app never flashes the wrong theme. Since the design
the default is **parchment**, whatever the device prefers; `contrast.test.ts`
holds the script, `theme.ts` and the tokens to the same answer.

## Still open

- **A splash screen.** iOS wants raster `apple-touch-startup-image` files
  rather than the SVG the manifest carries, so the seal has to be rasterised
  at build time. Raster icon generation belongs with the build, which is the deployment's,
  so this one needs a conversation rather than a file.
- **`scenario` on `/healthz`.** The cache name reads it already; the API does
  not serve it yet. Asked of A in the earlier pull request.
