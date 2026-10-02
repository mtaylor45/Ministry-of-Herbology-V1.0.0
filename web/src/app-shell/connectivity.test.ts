import { describe, expect, it } from 'vitest';
import { INITIAL, reduce, sentence, shouldNotice, type Connectivity } from './connectivity';

const fmt = (iso: string) => `at ${iso}`;

describe('the connectivity reducer', () => {
  it('starts online with nothing from the cache, and shows no notice', () => {
    expect(INITIAL).toEqual({ online: true, fromCache: null });
    expect(shouldNotice(INITIAL)).toBe(false);
  });

  it('notices going offline and coming back', () => {
    const off = reduce(INITIAL, { type: 'offline' });
    expect(off.online).toBe(false);
    expect(shouldNotice(off)).toBe(true);
    const on = reduce(off, { type: 'online' });
    expect(on.online).toBe(true);
    expect(shouldNotice(on)).toBe(false);
  });

  it('notices a read served from the copy, and clears it on the next fresh read', () => {
    const stale = reduce(INITIAL, { type: 'moh:from-cache', cachedAt: '2026-10-01T06:00:00Z' });
    expect(stale.fromCache).toEqual({ cachedAt: '2026-10-01T06:00:00Z', what: 'data' });
    expect(shouldNotice(stale)).toBe(true);
    expect(reduce(stale, { type: 'moh:fresh' }).fromCache).toBeNull();
  });

  it('a page from the copy outranks the reads inside it', () => {
    const page = reduce(INITIAL, { type: 'moh:page-from-cache', cachedAt: '2026-10-01T05:00:00Z' });
    const alsoData = reduce(page, { type: 'moh:from-cache', cachedAt: '2026-10-01T06:00:00Z' });
    expect(alsoData.fromCache).toEqual({ cachedAt: '2026-10-01T05:00:00Z', what: 'page' });
    // and one fresh read inside a cached page does not make the page fresh
    expect(reduce(alsoData, { type: 'moh:fresh' }).fromCache?.what).toBe('page');
  });

  it('starts each navigation honest', () => {
    const page = reduce(INITIAL, { type: 'moh:page-from-cache', cachedAt: null });
    expect(reduce(page, { type: 'navigated' }).fromCache).toBeNull();
  });

  it('keeps a copy that did not say when it was saved', () => {
    expect(reduce(INITIAL, { type: 'moh:from-cache' }).fromCache).toEqual({
      cachedAt: null,
      what: 'data',
    });
  });
});

describe('what the notice says', () => {
  const copy: Connectivity = {
    online: false,
    fromCache: { cachedAt: '2026-10-01T06:00:00Z', what: 'page' },
  };

  it('says offline and how old the copy is, and that nothing is sent', () => {
    expect(sentence(copy, fmt)).toBe(
      'You are offline. This is the copy saved at 2026-10-01T06:00:00Z. ' +
        'Nothing you mark here is sent until the signal returns.',
    );
  });

  it('says offline on its own when nothing came from the copy yet', () => {
    expect(sentence({ online: false, fromCache: null }, fmt)).toMatch(/^You are offline\./);
  });

  it('does not claim to be offline when the browser says it is online', () => {
    const online = { ...copy, online: true };
    expect(sentence(online, fmt)).toBe(
      'The greenhouse did not answer, so this is the copy saved at 2026-10-01T06:00:00Z.',
    );
    expect(sentence(online, fmt)).not.toContain('offline');
  });

  it('does not invent a time the copy did not carry', () => {
    const undated = { online: false, fromCache: { cachedAt: null, what: 'data' as const } };
    expect(sentence(undated, fmt)).toContain('a copy saved on this device');
  });
});
