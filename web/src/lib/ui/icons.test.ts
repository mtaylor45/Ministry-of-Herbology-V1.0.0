/** Icons: original line art, decorative by default, never the only signal. */

import { describe, expect, it } from 'vitest';
import Icon from './Icon.svelte';
import { ICONS, ICON_NAMES } from './icons';
import { attrs, html } from './render';

describe('the icon set', () => {
  it('draws something for every name it offers', () => {
    expect(ICON_NAMES.length).toBeGreaterThan(12);
    for (const name of ICON_NAMES) {
      const spec = ICONS[name];
      expect(spec.paths.length, `${name} has no path data`).toBeGreaterThan(0);
      for (const path of spec.paths) expect(path).toMatch(/^M/);
      expect(spec.plain, `${name} has no plain name`).toBeTruthy();
    }
  });

  it('renders every icon without complaint', () => {
    for (const name of ICON_NAMES) {
      expect(html(Icon, { name })).toContain('<path');
    }
  });
});

describe('Icon', () => {
  it('is hidden from screen readers unless it is given a name', () => {
    const decorative = attrs(html(Icon, { name: 'leaf' }), 'svg');
    expect(decorative['aria-hidden']).toBe('true');
    expect(decorative.role).toBeUndefined();
  });

  it('becomes an image with a title when it carries meaning on its own', () => {
    const markup = html(Icon, { name: 'warning', title: 'Frost tonight' });
    expect(attrs(markup, 'svg').role).toBe('img');
    expect(markup).toContain('<title>Frost tonight</title>');
  });

  it('takes the colour of the text around it, so it inherits its contrast', () => {
    expect(attrs(html(Icon, { name: 'leaf' }), 'svg').stroke).toBe('currentColor');
  });

  it('fails loudly on a name that does not exist', () => {
    expect(() => html(Icon, { name: 'nimbus' })).toThrow(/nimbus/);
  });
});
