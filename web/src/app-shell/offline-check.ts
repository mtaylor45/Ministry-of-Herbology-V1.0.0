/** The offline check — `node src/app-shell/offline-check.ts`. The design system, an earlier release.
 *
 * Drives Chromium through the service worker's promises and prints what it
 * saw, so "verified offline" in a pull request is a transcript rather than a
 * claim. It needs the same two things the accessibility audit does — the API
 * in mock mode on `MOH_API_URL`, and `npm run build` — and starts the web app
 * behind the audit's proxy the same way. See `src/lib/ui/a11y/README.md`.
 *
 * What it checks, in order:
 *
 *   1. the worker installs and precaches the shell: the display font, the
 *      seal, the icons and the manifest are in the shell cache;
 *   2. Morning Rounds and a specimen's tending facet, once opened online, are
 *      kept, and the API reads behind them land in a cache named after the
 *      API's `contract_version` and `mode`;
 *   3. **never**: a GET under `/calendar/`, the feed list whose responses carry
 *      tokens, `/healthz`, and a POST — none of them leave a trace in any cache;
 *   4. offline, Rounds and the tending facet open from the copy and the shell
 *      says so; a page that was never opened gets the plain "not saved" page;
 *      a `/calendar/` fetch fails outright rather than answering from a cache;
 *   5. when `/healthz` names a different world (a scenario), the old API cache
 *      is dropped on the next page load.
 *
 * Exit code 1 on the first promise that does not hold.
 */

import { chromium, type BrowserContext, type Page } from 'playwright';

const SPECIMEN_ID = process.env.MOH_SPECIMEN_ID || '01890040-0000-7000-8000-000000000001';
const TENDING = `/specimen/${SPECIMEN_ID}/tending`;

// The audit's stack starter, imported by URL rather than by path: the project
// forbids `.ts` import extensions and Node needs one, and a computed specifier
// satisfies both. The type comes from the module itself.
const audit = (await import(
  new URL('../lib/ui/a11y/audit.ts', import.meta.url).href
)) as typeof import('../lib/ui/a11y/audit');

let failures = 0;
function check(ok: boolean, what: string): void {
  console.log(`${ok ? '  ok ' : '  FAIL'} ${what}`);
  if (!ok) failures += 1;
}

interface CacheListing {
  [cache: string]: string[];
}

/** Every cache this origin holds, with the paths inside each. */
async function listCaches(page: Page): Promise<CacheListing> {
  return page.evaluate(async () => {
    const out: Record<string, string[]> = {};
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      out[name] = (await cache.keys()).map((request) => new URL(request.url).pathname);
    }
    return out;
  });
}

function everyPath(listing: CacheListing): string[] {
  return Object.values(listing).flat();
}

/** A fetch made from inside the page, so it goes through the worker. */
async function fetchFromPage(
  page: Page,
  path: string,
  init: { method?: string } = {},
): Promise<{ status: number | null; error: string | null }> {
  return page.evaluate(
    async ({ path, init }) => {
      try {
        const response = await fetch(path, init);
        return { status: response.status, error: null };
      } catch (error) {
        return { status: null, error: String(error) };
      }
    },
    { path, init },
  );
}

async function waitForWorker(page: Page): Promise<void> {
  await page.evaluate(() => navigator.serviceWorker.ready);
  // `ready` resolves on activation; the precache happens in `install`, before
  // it, so by now the shell cache is complete.
}

async function noticeText(page: Page): Promise<string> {
  const notice = page.locator('[role="status"].offline');
  if ((await notice.count()) === 0) return '';
  return (await notice.first().innerText()).replace(/\s+/g, ' ').trim();
}

async function main(): Promise<number> {
  const ports = { web: await audit.freePort(), proxy: await audit.freePort() };
  let stack = await audit.startStack(ports);
  const executablePath = process.env.MOH_A11Y_CHROMIUM;
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const context: BrowserContext = await browser.newContext({
    viewport: { width: 375, height: 812 },
    hasTouch: true,
  });
  const page = await context.newPage();
  const origin = stack.origin;

  try {
    console.log('\n1. Install');
    await page.goto(`${origin}/`, { waitUntil: 'networkidle' });
    await waitForWorker(page);
    let caches = await listCaches(page);
    const shell = Object.keys(caches).find((name) => name.startsWith('moh-shell-'));
    check(Boolean(shell), `a shell cache exists: ${shell ?? 'none'}`);
    for (const path of [
      '/fonts/cormorant-garamond-latin.woff2',
      '/seal.svg',
      '/favicon.svg',
      '/icon-maskable.svg',
      '/manifest.webmanifest',
    ]) {
      check(Boolean(shell && caches[shell].includes(path)), `precached ${path}`);
    }
    check(
      Boolean(shell && caches[shell].some((path) => path.startsWith('/_app/immutable/'))),
      'precached the built app',
    );
    check(
      !everyPath(caches).some((path) => /\.(md|txt)$/.test(path)),
      'did not precache the font licence or README',
    );

    console.log('\n2. Pages and reads, online');
    // The first load above was not yet controlled by the worker. These are.
    await page.goto(`${origin}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    // Client-side navigation to the tending facet, so its reads go through the
    // worker's API path rather than being inlined by the server.
    const link = page.locator(`a[href="${TENDING}"]`).first();
    if ((await link.count()) > 0) {
      await link.click();
      await page.waitForURL(`**${TENDING}`);
    } else {
      await page.goto(`${origin}${TENDING}`);
    }
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    // And a full load of the facet, so its HTML is kept too.
    await page.goto(`${origin}${TENDING}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    caches = await listCaches(page);
    const api = Object.keys(caches).find((name) => name.startsWith('moh-api-'));
    check(Boolean(shell && caches[shell].includes('/')), 'kept the HTML of Morning Rounds');
    check(Boolean(shell && caches[shell].includes(TENDING)), `kept the HTML of ${TENDING}`);
    check(Boolean(api), `an API cache named after the API exists: ${api ?? 'none'}`);
    check(
      /^moh-api-\d+\.\d+\.\d+-(mock|live)/.test(api ?? ''),
      'its name carries version and mode',
    );
    const reads = api ? caches[api] : [];
    check(
      reads.some((path) => path === `/api/v1/specimens/${SPECIMEN_ID}`),
      `kept GET /api/v1/specimens/${SPECIMEN_ID}`,
    );
    console.log(`     reads kept: ${reads.join(', ') || '(none)'}`);

    console.log('\n3. Never');
    const before = everyPath(caches).length;
    const calendar = await fetchFromPage(page, '/api/v1/calendar/notatoken.ics');
    const feeds = await fetchFromPage(page, '/api/v1/tending/feeds');
    const health = await fetchFromPage(page, '/api/v1/healthz');
    const post = await fetchFromPage(page, '/api/v1/tending/rounds', { method: 'POST' });
    await page.waitForTimeout(300);
    caches = await listCaches(page);
    const paths = everyPath(caches);
    console.log(
      `     calendar ${calendar.status}, feeds ${feeds.status}, healthz ${health.status}, POST ${post.status}`,
    );
    check(!paths.some((path) => path.includes('/calendar/')), 'nothing under /calendar/ is cached');
    check(!paths.some((path) => path.endsWith('/tending/feeds')), 'the feed list is not cached');
    check(!paths.some((path) => path.endsWith('/healthz')), '/healthz is not cached');
    check(
      paths.length === before,
      `no new entry from any of them (${before} before, ${paths.length} after)`,
    );

    console.log('\n4. Offline');
    // Playwright's offline emulation reaches the page but not the worker's own
    // fetches in this Chromium — the worker kept getting answers from the
    // server with the page "offline". So the servers are stopped for real,
    // which is what a garden with no signal looks like to a worker, and the
    // emulation is kept only so `navigator.onLine` tells the shell the truth.
    await stack.stop();
    await context.setOffline(true);
    const rounds = await page.goto(`${origin}/`);
    await page.waitForLoadState('load');
    await page.waitForTimeout(600);
    check(rounds?.status() === 200, `Morning Rounds opened offline (HTTP ${rounds?.status()})`);
    check(
      (await page.locator('h1').first().innerText()).includes('Morning Rounds'),
      'and it is Morning Rounds',
    );
    let notice = await noticeText(page);
    check(notice.includes('You are offline'), `the shell says so: "${notice}"`);
    check(notice.includes('copy saved'), 'and names the copy');

    const tending = await page.goto(`${origin}${TENDING}`);
    await page.waitForLoadState('load');
    await page.waitForTimeout(600);
    check(
      tending?.status() === 200,
      `the tending facet opened offline (HTTP ${tending?.status()})`,
    );
    check(
      (await page.locator('main').innerText()).includes('care profile') ||
        (await page.locator('main').innerText()).includes('Care values'),
      'with the care profile on it',
    );

    const never = await page.goto(`${origin}/almanac`);
    await page.waitForLoadState('load');
    const body = await page.locator('body').innerText();
    check(
      never?.status() === 503,
      `a page never opened gets the not-saved page (HTTP ${never?.status()})`,
    );
    check(body.includes('You are offline') && body.includes('never opened'), 'which says why');

    await page.goto(`${origin}/`);
    await page.waitForLoadState('load');
    const offlineCalendar = await fetchFromPage(page, '/api/v1/calendar/notatoken.ics');
    check(
      offlineCalendar.status === null,
      `a /calendar/ fetch offline fails rather than answering from a cache (${offlineCalendar.error})`,
    );
    const offlineHealth = await fetchFromPage(page, '/api/v1/healthz');
    check(offlineHealth.status === null, 'and so does /healthz');
    const offlineRead = await fetchFromPage(page, `/api/v1/specimens/${SPECIMEN_ID}`);
    check(
      offlineRead.status === 200,
      `a kept read answers from the copy (HTTP ${offlineRead.status})`,
    );

    // Back online, the notice should go.
    stack = await audit.startStack(ports);
    await context.setOffline(false);
    await page.goto(`${origin}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    notice = await noticeText(page);
    check(notice === '', `back online, the notice is gone${notice ? `: "${notice}"` : ''}`);

    console.log('\n5. A different world');
    // Make /healthz say the API is running another scenario and see the cache
    // named after the old one dropped. Routed at the context so the worker's
    // own fetch is answered too.
    await context.route('**/api/v1/healthz', (route) =>
      route.fulfill({
        json: { status: 'ok', contract_version: '1.6.0', mode: 'mock', scenario: 'drought' },
      }),
    );
    await page.goto(`${origin}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    caches = await listCaches(page);
    let names = Object.keys(caches).filter((name) => name.startsWith('moh-api-'));
    console.log(`     API caches after the page load: ${names.join(', ') || '(none)'}`);
    check(!names.includes(api ?? ''), `the ${api} cache was dropped on the next page load`);
    // The cache for the new world is opened by the first read that goes into
    // it, not by the rename itself.
    const read = await fetchFromPage(page, `/api/v1/specimens/${SPECIMEN_ID}`);
    await page.waitForTimeout(300);
    caches = await listCaches(page);
    names = Object.keys(caches).filter((name) => name.startsWith('moh-api-'));
    console.log(`     after one read (HTTP ${read.status}): ${names.join(', ') || '(none)'}`);
    check(
      names.includes('moh-api-1.6.0-mock-drought'),
      'and the next read lands in one named for the scenario',
    );
    check(names.length === 1, 'and it is the only API cache');
  } finally {
    await browser.close();
    await stack.stop();
  }

  console.log(failures ? `\n${failures} promise(s) did not hold.` : '\nEvery promise held.');
  return failures ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error: unknown) => {
    console.error(error instanceof Error ? (error.stack ?? error.message) : error);
    process.exit(2);
  },
);
