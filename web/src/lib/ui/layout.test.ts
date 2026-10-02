/** Card and ListRow: one tap target per row, and headings that nest. */

import { describe, expect, it } from 'vitest';
import Card from './Card.svelte';
import ListRow from './ListRow.svelte';
import { attrs, count, html, text } from './render';

const body = () => {};

describe('Card', () => {
  it('renders a heading at the level it is given, so pages keep an outline', () => {
    expect(html(Card, { plain: 'Inventory', children: body })).toContain('<h2');
    expect(html(Card, { plain: 'Inventory', level: 3, children: body })).toContain('<h3');
    expect(html(Card, { plain: 'Inventory', level: 4, children: body })).toContain('<h4');
  });

  it('goes without a header rather than inventing one', () => {
    const markup = html(Card, { children: body });
    expect(count(markup, 'h2')).toBe(0);
    expect(count(markup, 'header')).toBe(0);
  });

  it('pairs its themed title with a plain one', () => {
    const markup = html(Card, { themed: 'The Register', plain: 'Inventory', children: body });
    expect(text(markup)).toContain('The Register');
    expect(text(markup)).toContain('Inventory');
    expect(() => html(Card, { themed: 'The Register', children: body })).toThrow(/Card/);
  });
});

describe('ListRow', () => {
  it('is one tap target, not a row of little ones', () => {
    const markup = html(ListRow, {
      plain: 'Sweet basil',
      href: '/specimen/1',
      meta: 'Kitchen sill',
    });
    expect(count(markup, 'a')).toBe(1);
    expect(count(markup, 'button')).toBe(0);
    expect(attrs(markup, 'a').href).toBe('/specimen/1');
  });

  it('becomes a button when it acts rather than navigates', () => {
    const markup = html(ListRow, { plain: 'Pick this one', onclick: () => {} });
    expect(count(markup, 'button')).toBe(1);
    expect(count(markup, 'a')).toBe(0);
  });

  it('is a plain div when it does nothing, so nothing is falsely clickable', () => {
    const markup = html(ListRow, { plain: 'Sweet basil' });
    expect(count(markup, 'a')).toBe(0);
    expect(count(markup, 'button')).toBe(0);
  });

  it('marks selection for assistive technology, not only with a tint', () => {
    expect(
      attrs(html(ListRow, { plain: 'Row', href: '/x', selected: true }), 'a')['aria-current'],
    ).toBe('true');
    expect(
      attrs(html(ListRow, { plain: 'Row', onclick: () => {}, selected: true }), 'button')[
        'aria-pressed'
      ],
    ).toBe('true');
  });

  it('disables the control rather than only fading it', () => {
    const markup = html(ListRow, { plain: 'Row', onclick: () => {}, disabled: true });
    expect(attrs(markup, 'button')).toHaveProperty('disabled');
  });

  it('keeps its meta line plain and its themed name paired', () => {
    const markup = html(ListRow, {
      themed: 'Sweet basil',
      plain: 'Ocimum basilicum',
      meta: 'Kitchen sill · indoors',
    });
    expect(text(markup)).toContain('Ocimum basilicum');
    expect(text(markup)).toContain('Kitchen sill · indoors');
    expect(() => html(ListRow, { themed: 'Sweet basil' })).toThrow(/ListRow/);
  });
});
