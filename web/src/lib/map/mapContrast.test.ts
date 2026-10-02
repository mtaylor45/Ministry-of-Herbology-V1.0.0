/** A pin has to be visible on a sheet this app has never seen.
 *
 * The design system's `contrast.test.ts` covers text on the app's own surfaces. A
 * map marker is a different problem: it sits on an operator's scan, and the
 * scan can be any colour at all. WCAG 1.4.11 asks 3:1 of a graphical object
 * you need to be able to see, and a marker you cannot find is a marker that
 * does not work.
 *
 * The first cut of this component tinted the pin `--moh-accent` with a
 * surface-coloured border. Measured in the running app at 375px, that came
 * out at 5.72:1 on a pale plan in parchment and **2.10:1 in greenhouse** — a
 * real failure, in this branch, found by measuring rather than by looking.
 * Re-tinting would only have moved it to a differently-coloured sheet.
 *
 * The fix is the one map markers have always used: a light ring and a dark
 * one. `--moh-surface-raised` and `--moh-ink` sit at opposite ends of
 * whichever theme is on, so whatever is underneath, one of the two clears
 * 3:1. This module asserts that property against the tokens themselves —
 * including against a grey chosen to be as awkward as possible for both.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const tokensCss = readFileSync(fileURLToPath(new URL('../ui/tokens.css', import.meta.url)), 'utf8');
const componentCss = readFileSync(
  fileURLToPath(new URL('./GroundsMap.svelte', import.meta.url)),
  'utf8',
);

function tokens(selector: string): Record<string, string> {
  const start = tokensCss.indexOf(selector);
  if (start === -1) throw new Error(`no block for ${selector}`);
  const block = tokensCss.slice(tokensCss.indexOf('{', start) + 1, tokensCss.indexOf('}', start));
  const found: Record<string, string> = {};
  for (const line of block.split('\n')) {
    const match = /^\s*(--moh-[\w-]+):\s*([^;]+);/.exec(line);
    if (match) found[match[1]] = match[2].trim();
  }
  return found;
}

function channel(value: number): number {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const clean = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const THEMES: [string, Record<string, string>][] = [
  ['parchment', tokens("[data-theme='parchment']")],
  ['greenhouse', tokens("[data-theme='greenhouse']")],
];

/** Sheets a pin might land on, including the ones chosen to be hardest.
 *
 * `#767676` is the mid grey that is the worst case for a light/dark pair: it
 * is roughly equidistant from black and white, so neither ring gets an easy
 * ride. If the rule holds here it holds on a scan of anything.
 */
const SHEETS: [string, string][] = [
  ['a pale scan', '#ececec'],
  ['white paper', '#ffffff'],
  ['mid grey', '#767676'],
  ['the worst grey for a light/dark pair', '#949494'],
  ['a dark aerial', '#1a1a1a'],
  ['black', '#000000'],
];

/** WCAG 1.4.11, non-text contrast. */
const GRAPHICAL_MINIMUM = 3;

describe('the pin is findable on a sheet nobody chose', () => {
  it.each(
    THEMES.flatMap(([theme, token]) =>
      SHEETS.map(([where, sheet]) => [theme, where, token, sheet] as const),
    ),
  )('%s, on %s', (_theme, _where, token, sheet) => {
    const best = Math.max(
      ratio(token['--moh-ink'], sheet),
      ratio(token['--moh-surface-raised'], sheet),
    );
    expect(best).toBeGreaterThanOrEqual(GRAPHICAL_MINIMUM);
  });

  it.each(THEMES)('%s: the dot is legible against its own inner ring', (_theme, token) => {
    expect(ratio(token['--moh-accent'], token['--moh-surface-raised'])).toBeGreaterThanOrEqual(
      GRAPHICAL_MINIMUM,
    );
  });

  it.each(THEMES)('%s: the selected hue cannot carry selection on its own', (_theme, token) => {
    // Measured, not assumed: `--moh-parched` against `--moh-accent` is
    // 1.44:1 in parchment and 1.03:1 in greenhouse. Two colours that close
    // mark nothing for anyone. This asserts the *weakness*, so that if the design system's
    // palette ever moves and the pair becomes distinguishable, somebody
    // revisits the note below rather than leaving a stale comment behind.
    expect(ratio(token['--moh-parched'], token['--moh-accent'])).toBeLessThan(3);
  });

  it('marks a selected pin by size, because the hue pair cannot', () => {
    const selected = componentCss.slice(
      componentCss.indexOf('.moh-pin-dot.is-selected)'),
      componentCss.indexOf('.moh-pin:focus-visible'),
    );
    // Something other than `background` has to change, or selection is
    // colour alone — which this design system does not allow anywhere.
    expect(selected).toMatch(/\bwidth:/);
    expect(selected).toMatch(/\bheight:/);
  });

  it('draws the two rings the rule above depends on', () => {
    // A guard aimed at nothing is worse than no guard (the design addendum
    // makes that point at length). So this checks the component actually
    // carries the light-and-dark pair the ratios above are computed from.
    const pin = componentCss.slice(
      componentCss.indexOf('.moh-pin-dot)'),
      componentCss.indexOf('.moh-pin:focus-visible'),
    );
    expect(pin).toContain('--moh-surface-raised');
    expect(pin).toContain('--moh-ink');
  });
});

describe('the map uses tokens, never literals', () => {
  it('has no hex colour anywhere in its styles', () => {
    // The design system re-pigmented the whole palette on 29 Sept and cleared a
    // 1.26:1 violation that had been shipping for releases.
    // A literal in here would have survived that, which is the point.
    const styles = componentCss.slice(componentCss.indexOf('<style>'));
    const literals = styles.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\((?!\s*var)/g) ?? [];
    expect(literals).toEqual([]);
  });
});
