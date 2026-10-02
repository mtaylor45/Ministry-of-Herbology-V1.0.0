/** What the service worker may keep, and under what name. The design system, an earlier release.
 *
 * The decisions live here, as plain functions with no worker globals in them,
 * so `cache-policy.test.ts` can hold them to the three hard rules without a
 * browser:
 *
 *   1. **never cache a mutating request** — only GET is ever stored;
 *   2. **never cache any URL under `/calendar/`** — the calendar-feed token is
 *      the one credential the app issues to a person and it travels in that
 *      URL, so a cache entry would be a credential on disk;
 *   3. **never cache `/healthz`** — a stale "ok" would hide a dead API.
 *
 * Beyond those, the cache is an allowlist, not a denylist. The offline scope
 * decided is *care instructions and the current Morning Rounds*; maps,
 * charts and photos are not cached, and neither is anything this file does not
 * name.
 */

/** The API's own description of itself, from `/api/v1/healthz`. `scenario` is
 *  not served yet — the maintainers is asked for it — but it is read here already so that a
 *  frost-scenario round cannot outlive a switch to drought once it is. */
export interface ApiHealth {
  status?: string;
  contract_version?: string;
  mode?: string;
  scenario?: string;
}

export const API_BASE = '/api/v1';

/** The responses Morning Rounds and a specimen's tending facet are built from.
 *  Each is a GET under `/api/v1` with no credential in it. */
const CACHEABLE_API: RegExp[] = [
  /^\/tending\/rounds$/,
  /^\/tending\/tasks$/,
  /^\/tending\/care-rules$/,
  /^\/specimens$/,
  /^\/specimens\/[^/]+$/,
  /^\/species\/[^/]+$/,
  /^\/species\/[^/]+\/care-values$/,
  // Rounds reads the household roster to offer a name at completion. It is a
  // furnishing, not the round — but an empty picker offline is a worse one.
  /^\/members$/,
];

/** The pages whose server-rendered HTML is kept, so they open with no signal.
 *  Rounds, and the three facets of a specimen that carry its care. The journal
 *  facet is left out on purpose: it is plates and photos. */
const CACHEABLE_PAGES: RegExp[] = [
  /^\/$/,
  /^\/specimen\/[^/]+$/,
  /^\/specimen\/[^/]+\/(register|tending|compendium)$/,
];

/** The ownership rule. Anywhere in the path, not only at one position: a route added
 *  later with the token in a different place must still be refused. */
export function carriesCalendarToken(pathname: string): boolean {
  return pathname.includes('/calendar/');
}

/** The build-against-mocks rule. */
export function isHealthz(pathname: string): boolean {
  return /\/healthz$/.test(pathname);
}

/** An API read the worker may serve stale while it revalidates. */
export function isCacheableApi(url: URL, method: string, origin: string): boolean {
  if (method.toUpperCase() !== 'GET') return false; // The contract-first rule
  if (url.origin !== origin) return false;
  if (carriesCalendarToken(url.pathname)) return false; // The ownership rule
  if (isHealthz(url.pathname)) return false; // The build-against-mocks rule
  if (!url.pathname.startsWith(`${API_BASE}/`)) return false;
  const path = url.pathname.slice(API_BASE.length);
  return CACHEABLE_API.some((pattern) => pattern.test(path));
}

/** A page whose HTML the worker keeps a copy of. */
export function isCacheablePage(url: URL, method: string, origin: string): boolean {
  if (method.toUpperCase() !== 'GET') return false;
  if (url.origin !== origin) return false;
  if (carriesCalendarToken(url.pathname)) return false;
  return CACHEABLE_PAGES.some((pattern) => pattern.test(url.pathname));
}

export const API_CACHE_PREFIX = 'moh-api-';

/** The API cache is named after what the API says it is. A different contract
 *  version, a switch between mock and live, or — once the maintainers serves it — a different
 *  scenario, is a different cache, and the old one is dropped. A cached round
 *  from the frost scenario must not survive a switch to drought. */
export function apiCacheName(health: ApiHealth): string | null {
  if (health.status !== 'ok' || !health.contract_version || !health.mode) return null;
  const parts = [health.contract_version, health.mode];
  if (health.scenario) parts.push(health.scenario);
  return `${API_CACHE_PREFIX}${parts.map(safe).join('-')}`;
}

function safe(part: string): string {
  return part.replace(/[^a-z0-9.]+/gi, '_');
}

/** Static files worth having before they are asked for. The licence and the
 *  README beside the font are not. */
export function worthPrecaching(path: string): boolean {
  return !/\.(md|txt)$/i.test(path);
}

export const PAGE_CACHE_PREFIX = 'moh-shell-';

/** The caches a new worker version deletes on activation: every one of ours
 *  except the two it is about to use. */
export function cachesToDrop(names: string[], keep: (string | null)[]): string[] {
  return names.filter(
    (name) =>
      (name.startsWith(API_CACHE_PREFIX) || name.startsWith(PAGE_CACHE_PREFIX)) &&
      !keep.includes(name),
  );
}
