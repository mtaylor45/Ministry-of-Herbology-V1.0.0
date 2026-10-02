/** The gallery is the design system's own front door: if a component is not in
 *  it, nobody can see what it looks like in the other theme. */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import Gallery from './Gallery.svelte';
import { THEMES } from '../theme';
import { html, text } from '../render';

const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8');
const pane = read('./GalleryPane.svelte');
const index = read('../index.ts');

/** Components the gallery shows through something else rather than on its own. */
const SHOWN_INDIRECTLY = new Set([
  'Nav', // the app shell's navigation; it belongs to the shell, not to a panel
  'Field', // the label/hint/error wrapper every field primitive renders through
  'Label', // the pairing primitive every component renders through
]);

const exported = [...index.matchAll(/export \{ default as (\w+) \}/g)].map((match) => match[1]);

describe('the component gallery', () => {
  it('shows both themes on the one page', () => {
    const markup = html(Gallery, {});
    for (const theme of THEMES) expect(markup).toContain(`data-theme="${theme}"`);
  });

  it('shows every component the library exports', () => {
    const missing = exported.filter(
      (name) => !SHOWN_INDIRECTLY.has(name) && !pane.includes(`<${name}`),
    );
    expect(missing).toEqual([]);
    expect(exported.length).toBeGreaterThan(15);
  });

  it('runs on its own — no API, no fixtures, no store', () => {
    // "Visible in both themes at once without running the whole app" means the
    // page must not import anything that needs a server behind it.
    const sources = [pane, read('./samples.ts'), read('./Gallery.svelte')].flatMap((file) =>
      [...file.matchAll(/from '([^']+)'/g)].map((match) => match[1]),
    );
    expect(sources.length).toBeGreaterThan(0);
    for (const source of sources) {
      expect(source, `the gallery imports ${source}`).not.toMatch(/\$api|fixtures|\$app\//);
    }
  });

  it('renders each control in its ordinary and its awkward states', () => {
    const markup = text(html(Gallery, {}));
    for (const state of ['Saving', 'Unavailable', 'Error:', 'Loading', 'Out of date', 'Done']) {
      expect(markup, `the gallery never shows the "${state}" state`).toContain(state);
    }
  });

  it('pairs every themed string it shows, because it is the example', () => {
    // Every Label in the pane render carries both halves, or the render throws.
    expect(() => html(Gallery, {})).not.toThrow();
  });
});
