/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

/** The service worker — care instructions available offline. The design system, an earlier release.
 *
 * Three jobs, in `fetch` order:
 *
 *   1. **The shell.** Everything Vite built plus the static files worth having
 *      (the display font, the seal, the icons, the manifest) is precached on
 *      install under this build's `version`, and served cache-first. A new
 *      deployment is a new cache; the old one is dropped on activation.
 *
 *   2. **Pages.** Morning Rounds and a specimen's register, tending and
 *      compendium facets are kept as their server-rendered HTML, so they open
 *      with no signal. Network first: a page that can be fetched is fetched,
 *      and the copy is refreshed; one that cannot is served from the copy, and
 *      the shell is told so it can say so. Anything else offline gets a plain
 *      page that says it was never saved.
 *
 *   3. **API reads.** The GETs those pages are built from — see
 *      `app-shell/cache-policy.ts` for the list — are kept under a cache named
 *      after the API's own `contract_version` and `mode` (and `scenario`, once
 *      it is served), so a round cached from one world cannot be shown in
 *      another. A copy younger than a minute is served at once and refreshed
 *      behind it; an older one is served only when the network does not answer,
 *      and the shell is told. Plain stale-while-revalidate was asked for, and
 *      is not quite what this is: a SvelteKit page does not re-render when a
 *      background refresh lands, so serving a day-old round "while
 *      revalidating" is serving a day-old round, and the offline notice would
 *      have to show on every navigation to stay honest. A minute covers the
 *      specimen page's polling and a quick back-and-forth; past that, the
 *      network is asked first.
 *
 * Three things are never cached, and the policy module's tests hold the line:
 * a mutating request; any URL under `/calendar/`, because the feed token is in
 * it; and `/healthz`, so a stale "ok" cannot hide a dead API.
 */

import { build, files, version } from '$service-worker';
import {
  apiCacheName,
  cachesToDrop,
  carriesCalendarToken,
  isCacheableApi,
  isCacheablePage,
  isHealthz,
  worthPrecaching,
  PAGE_CACHE_PREFIX,
  type ApiHealth,
} from './app-shell/cache-policy';

const sw = self as unknown as ServiceWorkerGlobalScope;

const SHELL = `${PAGE_CACHE_PREFIX}${version}`;
/** Not prefixed like the others, so `cachesToDrop` leaves it alone: it holds
 *  one entry, the name of the API cache the last reachable `/healthz` named. */
const META = 'moh-meta';
const META_KEY = '/__moh/api-cache-name';
const PRECACHE = [...build, ...files.filter(worthPrecaching)];

/** Stamped on every stored copy, so the shell can say how old it is. */
const CACHED_AT = 'x-moh-cached-at';
/** How long an API copy is served without asking the network first. */
const FRESH_MS = 60_000;
/** How long the network gets before a stored page or read is used instead. */
const NETWORK_TIMEOUT_MS = 8_000;

// ----------------------------------------------------------------- lifecycle

sw.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL);
      await cache.addAll(PRECACHE);
      await sw.skipWaiting();
    })(),
  );
});

sw.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const apiName = await currentApiCacheName();
      const names = await caches.keys();
      await Promise.all(cachesToDrop(names, [SHELL, apiName]).map((name) => caches.delete(name)));
      await sw.clients.claim();
    })(),
  );
});

// ------------------------------------------------------------ the API cache

let knownApiCacheName: string | null = null;

/** Ask the API what it is, name the cache after it, and drop the caches of
 *  any other world. Falls back to the last name it managed to store when the
 *  API cannot be reached — which is exactly when the cache is needed. */
async function currentApiCacheName(): Promise<string | null> {
  try {
    const response = await fetch(`/api/v1/healthz`, { cache: 'no-store' });
    if (response.ok) {
      const name = apiCacheName((await response.json()) as ApiHealth);
      if (name) {
        if (name !== knownApiCacheName) {
          knownApiCacheName = name;
          const meta = await caches.open(META);
          await meta.put(META_KEY, new Response(name));
          const names = await caches.keys();
          await Promise.all(
            cachesToDrop(names, [SHELL, name])
              .filter((other) => !other.startsWith(PAGE_CACHE_PREFIX))
              .map((other) => caches.delete(other)),
          );
        }
        return name;
      }
    }
  } catch {
    // unreachable: fall through to what we knew
  }
  if (knownApiCacheName) return knownApiCacheName;
  const stored = await (await caches.open(META)).match(META_KEY);
  knownApiCacheName = stored ? await stored.text() : null;
  return knownApiCacheName;
}

// ------------------------------------------------------------------- fetch

sw.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // The contract-first rule, and the two paths the worker must never so much as look at. Not
  // calling respondWith leaves the request to the browser, untouched.
  if (request.method !== 'GET') return;
  if (url.origin !== sw.location.origin) return;
  if (carriesCalendarToken(url.pathname) || isHealthz(url.pathname)) return;

  if (PRECACHE.includes(url.pathname)) {
    event.respondWith(shellFirst(request));
  } else if (request.mode === 'navigate') {
    event.respondWith(page(event, url));
  } else if (isCacheableApi(url, request.method, sw.location.origin)) {
    event.respondWith(apiRead(event, url));
  }
});

async function shellFirst(request: Request): Promise<Response> {
  const cache = await caches.open(SHELL);
  return (await cache.match(request)) ?? fetch(request);
}

/** Pages served from the copy, by the id of the page that received one. The
 *  page does not exist yet while its response is being chosen, so it asks on
 *  load (`moh:hello`) and is answered from here. */
const pagesFromCache = new Map<string, string | null>();

async function page(event: FetchEvent, url: URL): Promise<Response> {
  const { request } = event;
  const cache = await caches.open(SHELL);
  const keep = isCacheablePage(url, request.method, sw.location.origin);
  try {
    const response = await withTimeout(fetch(request), NETWORK_TIMEOUT_MS);
    if (keep && response.ok) event.waitUntil(cache.put(request, stamp(response.clone())));
    // Every page load is a chance to notice the API has become a different
    // world since the cache was named.
    event.waitUntil(currentApiCacheName());
    return response;
  } catch {
    const cached = keep ? await cache.match(request) : undefined;
    if (cached) {
      pagesFromCache.set(event.resultingClientId, cached.headers.get(CACHED_AT));
      return cached;
    }
    return offlinePage(url);
  }
}

async function apiRead(event: FetchEvent, url: URL): Promise<Response> {
  const { request } = event;
  const name = await currentApiCacheName();
  const cache = name ? await caches.open(name) : null;
  const cached = (await cache?.match(request)) ?? null;
  const cachedAt = cached?.headers.get(CACHED_AT) ?? null;

  const revalidate = async (): Promise<Response> => {
    const response = await fetch(request);
    if (cache && response.ok) await cache.put(request, stamp(response.clone()));
    return response;
  };

  if (cached && ageOf(cachedAt) < FRESH_MS) {
    event.waitUntil(revalidate().catch(() => undefined));
    return cached;
  }
  try {
    const response = await withTimeout(revalidate(), NETWORK_TIMEOUT_MS);
    tell(event.clientId, { type: 'moh:fresh', url: url.pathname });
    return response;
  } catch (error) {
    if (!cached) throw error;
    tell(event.clientId, { type: 'moh:from-cache', url: url.pathname, cachedAt });
    return cached;
  }
}

// ------------------------------------------------------------------ helpers

function ageOf(cachedAt: string | null): number {
  const when = cachedAt ? Date.parse(cachedAt) : NaN;
  return Number.isFinite(when) ? Date.now() - when : Number.POSITIVE_INFINITY;
}

/** A copy of the response with the time it was stored, and without the
 *  transfer headers that describe bytes the Cache API no longer holds. */
function stamp(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.delete('content-encoding');
  headers.delete('content-length');
  headers.set(CACHED_AT, new Date().toISOString());
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function withTimeout<T>(work: Promise<T>, ms: number): Promise<T> {
  return new Promise((done, fail) => {
    const timer = setTimeout(() => fail(new Error(`no answer in ${ms}ms`)), ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        done(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        fail(error);
      },
    );
  });
}

async function tell(clientId: string, message: Record<string, unknown>): Promise<void> {
  if (!clientId) return;
  const client = await sw.clients.get(clientId);
  client?.postMessage(message);
}

sw.addEventListener('message', (event) => {
  const data = event.data as { type?: string } | null;
  const source = event.source as Client | null;
  if (data?.type !== 'moh:hello' || !source) return;
  if (pagesFromCache.has(source.id)) {
    source.postMessage({ type: 'moh:page-from-cache', cachedAt: pagesFromCache.get(source.id) });
    pagesFromCache.delete(source.id);
  }
});

/** Shown for a page that was never saved on this device. System colours only:
 *  there is no stylesheet to take tokens from here, and the rule that no colour
 *  literal lives outside `tokens.css` holds in a worker too. */
function offlinePage(url: URL): Response {
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not saved on this device — The Ministry of Herbology</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; min-height: 100dvh; display: grid; place-items: center;
         padding: 1.5rem; box-sizing: border-box; font-family: Georgia, serif;
         background: Canvas; color: CanvasText; line-height: 1.55; }
  main { max-width: 32rem; }
  h1 { font-size: 1.5rem; margin: 0 0 .5rem; }
  .plain { display: block; font-family: system-ui, sans-serif; font-size: .9rem; }
  a { color: LinkText; min-height: 44px; display: inline-flex; align-items: center; }
</style>
</head>
<body>
<main>
  <h1>The owls are grounded <span class="plain">You are offline</span></h1>
  <p>This page (<code>${escapeHtml(url.pathname)}</code>) was never opened while this device had a
  signal, so there is no saved copy to show.</p>
  <p>Morning Rounds, and the register, tending and compendium pages of any plant you have
  opened before, are kept on this device and will open without one.</p>
  <p><a href="/">Morning Rounds — back to today</a></p>
</main>
</body>
</html>`;
  return new Response(html, {
    status: 503,
    headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
  });
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
