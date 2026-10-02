/** The pairing rule is the one rule a component cannot be talked out of. */

import { describe, expect, it } from 'vitest';
import Label from './Label.svelte';
import { hasThemed, plainFirst, requirePair } from './pairing';
import { html, text } from './render';

describe('requirePair', () => {
  it('returns the plain string when both halves are there', () => {
    expect(requirePair('Parched', 'Water today', 'Test')).toBe('Water today');
  });

  it('allows a plain string on its own', () => {
    expect(requirePair(undefined, 'Water today', 'Test')).toBe('Water today');
  });

  it('refuses a themed string with no plain one, and names the component', () => {
    expect(() => requirePair('Parched', undefined, 'Button')).toThrow(/Button/);
    expect(() => requirePair('Parched', '   ', 'Button')).toThrow(/plain/i);
  });

  it('refuses an empty label outright', () => {
    expect(() => requirePair(undefined, '', 'Field')).toThrow(/plain-language label/);
  });
});

describe('plainFirst', () => {
  it('leads with the plain half, which is the half that carries meaning', () => {
    expect(plainFirst('Parched', 'Water today')).toBe('Water today (Parched)');
    expect(plainFirst(undefined, 'Water today')).toBe('Water today');
  });
});

describe('hasThemed', () => {
  it('treats blank themed strings as absent', () => {
    expect(hasThemed('  ')).toBe(false);
    expect(hasThemed('Parched')).toBe(true);
  });
});

describe('Label', () => {
  it('renders both halves', () => {
    expect(text(html(Label, { themed: 'Parched', plain: 'Water today' }))).toBe(
      'Parched Water today',
    );
  });

  it('keeps the plain half for screen readers when it is not shown', () => {
    const markup = html(Label, {
      themed: 'Parched',
      plain: 'Water today',
      display: 'screen-reader',
    });
    expect(markup).toContain('visually-hidden');
    expect(text(markup)).toContain('Water today');
  });

  it('never renders the themed half alone', () => {
    expect(() => html(Label, { themed: 'Parched' })).toThrow();
  });
});
