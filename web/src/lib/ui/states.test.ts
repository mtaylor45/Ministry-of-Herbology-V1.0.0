/** Empty, loading and stale: the three states a screen spends real time in.
 *
 *  The one that matters most is stale. Saying "here is the forecast" when the
 *  forecast is nine hours old is the kind of lie that gets a plant killed. */

import { describe, expect, it } from 'vitest';
import EmptyState from './EmptyState.svelte';
import Skeleton from './Skeleton.svelte';
import StaleNotice from './StaleNotice.svelte';
import { formatAsOf, staleSentence } from './stale';
import { attrs, count, html, text } from './render';

const NOW = new Date('2026-09-20T09:00:00Z');

describe('EmptyState', () => {
  it('says what is empty in plain words, with the themed line beside it', () => {
    const markup = html(EmptyState, {
      themed: 'The bed lies fallow',
      plain: 'No specimens here yet',
      body: 'Nothing has been planted in this zone.',
    });
    expect(text(markup)).toContain('No specimens here yet');
    expect(text(markup)).toContain('The bed lies fallow');
  });

  it('keeps its illustration out of the accessibility tree', () => {
    // The icon repeats the heading; announcing it twice helps nobody.
    expect(html(EmptyState, { plain: 'Nothing here' })).toContain('aria-hidden="true"');
  });

  it('refuses a themed line with no plain one', () => {
    expect(() => html(EmptyState, { themed: 'The bed lies fallow' })).toThrow(/EmptyState/);
  });
});

describe('Skeleton', () => {
  it('says what is loading out loud, because a grey bar says nothing', () => {
    const markup = html(Skeleton, { plain: 'Loading the Register…' });
    expect(attrs(markup, 'div')['aria-busy']).toBe('true');
    expect(attrs(markup, 'div').role).toBe('status');
    expect(text(markup)).toContain('Loading the Register…');
  });

  it('hides its bars from assistive technology and draws the asked-for number', () => {
    const markup = html(Skeleton, { lines: 4 });
    expect(count(markup, 'span')).toBe(5); // four bars plus the spoken line
    expect(markup).toContain('aria-hidden="true"');
  });
});

describe('formatAsOf', () => {
  it('counts in the units a person would use', () => {
    expect(formatAsOf(new Date('2026-09-20T08:59:30Z'), NOW)).toBe('moments ago');
    expect(formatAsOf(new Date('2026-09-20T08:59:00Z'), NOW)).toBe('1 minute ago');
    expect(formatAsOf(new Date('2026-09-20T08:20:00Z'), NOW)).toBe('40 minutes ago');
    expect(formatAsOf(new Date('2026-09-20T06:00:00Z'), NOW)).toBe('3 hours ago');
    expect(formatAsOf(new Date('2026-09-18T09:00:00Z'), NOW)).toBe('2 days ago');
  });

  it('says so plainly when there is nothing to be stale', () => {
    expect(formatAsOf(null, NOW)).toBe('never fetched');
    expect(formatAsOf('not a date', NOW)).toBe('never fetched');
  });

  it('does not pretend a clock skew into the future is old data', () => {
    expect(formatAsOf(new Date('2026-09-20T09:05:00Z'), NOW)).toBe('just now');
  });
});

describe('staleSentence', () => {
  it('names the data and its age, and never claims to be current', () => {
    const sentence = staleSentence('The Almanac forecast', new Date('2026-09-20T06:00:00Z'), NOW);
    expect(sentence).toBe('The Almanac forecast is the stored copy, last updated 3 hours ago.');
    expect(sentence).not.toMatch(/up to date|current|fresh/i);
  });

  it('admits when nothing was ever fetched', () => {
    expect(staleSentence('Soil moisture', null, NOW)).toBe(
      'Soil moisture has never been fetched on this device.',
    );
  });
});

describe('StaleNotice', () => {
  it('states the age of what it is showing', () => {
    const markup = html(StaleNotice, {
      plain: 'The Almanac forecast',
      asOf: new Date('2026-09-20T06:00:00Z'),
      now: NOW,
    });
    expect(text(markup)).toContain('last updated 3 hours ago');
    expect(attrs(markup, 'div').role).toBe('status');
  });

  it('says why, when it knows why', () => {
    const markup = html(StaleNotice, {
      plain: 'The Almanac forecast',
      asOf: null,
      now: NOW,
      reason: 'The weather service could not be reached.',
    });
    expect(text(markup)).toContain('has never been fetched');
    expect(text(markup)).toContain('The weather service could not be reached.');
  });

  it('offers a retry only when there is something to retry', () => {
    const without = html(StaleNotice, { plain: 'Forecast', asOf: null, now: NOW });
    expect(count(without, 'button')).toBe(0);
    const with_ = html(StaleNotice, { plain: 'Forecast', asOf: null, now: NOW, onretry: () => {} });
    expect(text(with_)).toContain('Try again');
  });
});
