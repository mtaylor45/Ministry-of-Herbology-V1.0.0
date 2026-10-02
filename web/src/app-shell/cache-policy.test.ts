/** The three hard rules of the offline cache, held without a browser. */

import { describe, expect, it } from 'vitest';
import {
  apiCacheName,
  cachesToDrop,
  carriesCalendarToken,
  isCacheableApi,
  isCacheablePage,
  worthPrecaching,
} from './cache-policy';

const ORIGIN = 'https://herbology.example';
const url = (path: string) => new URL(path, ORIGIN);
const api = (path: string, method = 'GET') => isCacheableApi(url(path), method, ORIGIN);

describe('the contract-first rule: never cache a mutating request', () => {
  it.each(['POST', 'PUT', 'PATCH', 'DELETE', 'post'])('refuses %s to a cacheable path', (m) => {
    expect(api('/api/v1/tending/rounds', m)).toBe(false);
    expect(isCacheablePage(url('/'), m, ORIGIN)).toBe(false);
  });

  it('keeps the GET the same path answers', () => {
    expect(api('/api/v1/tending/rounds')).toBe(true);
  });
});

describe('the ownership rule: never cache any URL under /calendar/', () => {
  // the feed token is the only credential the app issues to a
  // person, and it is in the URL. A cache entry would be a credential on disk.
  it.each([
    '/api/v1/calendar/abc123.ics',
    '/api/v1/calendar/',
    '/calendar/anything',
    '/api/v1/tending/calendar/feed',
    '/specimen/x/calendar/y',
  ])('refuses %s', (path) => {
    expect(carriesCalendarToken(path)).toBe(true);
    expect(api(path)).toBe(false);
    expect(isCacheablePage(url(path), 'GET', ORIGIN)).toBe(false);
  });

  it('is about the path segment, not the word', () => {
    // A query string mentioning a calendar is not a token in the path.
    expect(carriesCalendarToken('/api/v1/tending/tasks?view=calendar')).toBe(false);
  });
});

describe('the build-against-mocks rule: never cache /healthz', () => {
  it('refuses the health route however it is reached', () => {
    expect(api('/api/v1/healthz')).toBe(false);
    expect(isCacheableApi(url('/healthz'), 'GET', ORIGIN)).toBe(false);
  });
});

describe('the allowlist', () => {
  it.each([
    '/api/v1/tending/rounds',
    '/api/v1/tending/tasks',
    '/api/v1/tending/tasks?specimen_id=abc',
    '/api/v1/tending/care-rules?specimen_id=abc',
    '/api/v1/specimens',
    '/api/v1/specimens/01890040-0000-7000-8000-000000000001',
    '/api/v1/species/01890030-0000-7000-8000-000000000001',
    '/api/v1/species/01890030-0000-7000-8000-000000000001/care-values',
    '/api/v1/members',
  ])('keeps %s', (path) => {
    expect(api(path)).toBe(true);
  });

  it.each([
    // the earlier offline scope: maps, charts and photos are not cached.
    '/api/v1/specimens/abc/photos',
    '/api/v1/specimens/abc/log',
    '/api/v1/almanac/forecast',
    '/api/v1/almanac/frost',
    '/api/v1/almanac/water-balance/abc',
    '/api/v1/grounds/plans',
    '/api/v1/journal/coverage',
    '/api/v1/tending/feeds',
    '/api/v1/locations',
    // Not even close.
    '/api/v2/tending/rounds',
    '/tending/rounds',
  ])('leaves %s alone', (path) => {
    expect(api(path)).toBe(false);
  });

  it('never caches another origin', () => {
    expect(isCacheableApi(url('/api/v1/tending/rounds'), 'GET', 'https://elsewhere')).toBe(false);
    expect(isCacheableApi(new URL('https://cdn.example/api/v1/specimens'), 'GET', ORIGIN)).toBe(
      false,
    );
  });

  it.each([
    '/',
    '/specimen/abc',
    '/specimen/abc/register',
    '/specimen/abc/tending',
    '/specimen/abc/compendium',
  ])('keeps the page %s', (path) => {
    expect(isCacheablePage(url(path), 'GET', ORIGIN)).toBe(true);
  });

  it.each(['/specimen/abc/journal', '/journal', '/journal/abc', '/almanac', '/grounds', '/office'])(
    'does not keep the page %s',
    (path) => {
      expect(isCacheablePage(url(path), 'GET', ORIGIN)).toBe(false);
    },
  );
});

describe('the cache is named after the API', () => {
  it('keys on contract version and mode', () => {
    expect(apiCacheName({ status: 'ok', contract_version: '1.6.0', mode: 'mock' })).toBe(
      'moh-api-1.6.0-mock',
    );
    expect(apiCacheName({ status: 'ok', contract_version: '1.6.0', mode: 'live' })).toBe(
      'moh-api-1.6.0-live',
    );
  });

  it('keys on the scenario the moment the API says which it is running', () => {
    const frost = apiCacheName({
      status: 'ok',
      contract_version: '1.6.0',
      mode: 'mock',
      scenario: 'frost',
    });
    const drought = apiCacheName({
      status: 'ok',
      contract_version: '1.6.0',
      mode: 'mock',
      scenario: 'drought',
    });
    expect(frost).toBe('moh-api-1.6.0-mock-frost');
    expect(drought).not.toBe(frost);
  });

  it('names nothing for an API that is not ok, so nothing is served under a lie', () => {
    expect(
      apiCacheName({ status: 'degraded', contract_version: '1.6.0', mode: 'live' }),
    ).toBeNull();
    expect(apiCacheName({})).toBeNull();
  });

  it('drops every cache of ours but the two in use, and nothing that is not ours', () => {
    const names = [
      'moh-api-1.5.0-mock',
      'moh-api-1.6.0-mock',
      'moh-api-1.6.0-mock-frost',
      'moh-shell-old',
      'moh-shell-new',
      'workbox-precache',
    ];
    expect(cachesToDrop(names, ['moh-api-1.6.0-mock', 'moh-shell-new'])).toEqual([
      'moh-api-1.5.0-mock',
      'moh-api-1.6.0-mock-frost',
      'moh-shell-old',
    ]);
  });
});

describe('precaching', () => {
  it('takes the font, the seal and the icons, not the licence beside them', () => {
    expect(worthPrecaching('/fonts/cormorant-garamond-latin.woff2')).toBe(true);
    expect(worthPrecaching('/seal.svg')).toBe(true);
    expect(worthPrecaching('/manifest.webmanifest')).toBe(true);
    expect(worthPrecaching('/fonts/OFL.txt')).toBe(false);
    expect(worthPrecaching('/fonts/README.md')).toBe(false);
  });
});
