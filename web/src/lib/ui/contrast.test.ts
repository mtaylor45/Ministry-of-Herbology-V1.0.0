/** WCAG AA contrast, checked against the tokens themselves.
 *
 * Definition of done says the UI meets WCAG AA. A token is the one place a
 * contrast regression can enter for every screen at once, so it is the one
 * place worth testing exhaustively. The design system.
 *
 * an earlier release added the surfaces and colours the component library needs (fields,
 * selected rows, destructive actions) and the pairs that go with them.
 *
 * an earlier release added the half this file was missing. Measuring tokens against tokens only
 * proves the pairs somebody thought to list. It said nothing about where a
 * component actually paints one on the other — so `Label`'s plain half sat on
 * `--moh-ink-muted` while a primary button painted `--moh-accent` underneath it,
 * and 1.26:1 on parchment and 1.01:1 on greenhouse shipped and stayed shipped
 * for three releases. The `filled controls` block below walks the library's own
 * stylesheets, so a fill nobody measured cannot get through again.
 *
 * The rule has not moved: if a colour fails here, the colour changes, not the
 * threshold.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { DEFAULT_THEME_CHOICE, THEME_COLORS, THEME_STORAGE_KEY, THEMES } from './theme';

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const read = (path: string) => readFileSync(here(path), 'utf8');

const css = read('./tokens.css');
const fontsCss = read('./fonts.css');
const baseCss = read('./base.css');
const appHtml = read('../../app.html');

/** Strip CSS comments once, so nothing below matches a sentence in one. */
function uncomment(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Read one theme's token block, following one token's reference to another so
 *  `--moh-plain-ink: var(--moh-ink-muted)` arrives here as a colour. */
function tokens(selector: string): Record<string, string> {
  const source = uncomment(css);
  const start = source.indexOf(selector);
  if (start === -1) throw new Error(`no block for ${selector}`);
  const block = source.slice(source.indexOf('{', start) + 1, source.indexOf('}', start));
  const found: Record<string, string> = {};
  // Split on declarations, not on lines: prettier wraps a long font stack.
  for (const declaration of block.split(';')) {
    const match = /^\s*(--moh-[\w-]+):\s*([\s\S]+)$/.exec(declaration);
    if (match) found[match[1]] = match[2].replace(/\s+/g, ' ').trim();
  }
  for (let pass = 0; pass < 4; pass += 1) {
    for (const [key, value] of Object.entries(found)) {
      const reference = /^var\((--moh-[\w-]+)\)$/.exec(value);
      if (reference && found[reference[1]]) found[key] = found[reference[1]];
    }
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

/** A solid colour we can measure. `rgb(… / .55)` scrims are not one. */
function isOpaqueColour(value: string): boolean {
  return /^#[0-9a-f]{6}$/i.test(value);
}

const PARCHMENT = tokens("[data-theme='parchment']");
const GREENHOUSE = tokens("[data-theme='greenhouse']");

const THEME_TOKENS: [string, Record<string, string>][] = [
  ['parchment', PARCHMENT],
  ['greenhouse', GREENHOUSE],
];

/** Every surface a component in this library puts text on. */
const SURFACES = [
  '--moh-surface',
  '--moh-surface-raised',
  '--moh-surface-sunken',
  '--moh-field',
  '--moh-selected',
];

/** Inks that land on a page surface as body text. AA is 4.5:1.
 *
 * `--moh-plain-ink` is the plain half of a paired label. At the root it is the
 * muted ink; inside a filled control it is re-declared, and the `filled
 * controls` block below is what measures it there. */
const PAGE_INKS = [
  '--moh-ink',
  '--moh-ink-muted',
  '--moh-plain-ink',
  // Links and the quiet button's label are the accent, as text.
  '--moh-accent',
  // the design two derived pigments: gold that is allowed to be text, and sage.
  '--moh-gold-ink',
  '--moh-sage',
];

/** Body text: AA is 4.5:1. */
const BODY_PAIRS: [string, string][] = [
  ...SURFACES.flatMap((surface): [string, string][] =>
    PAGE_INKS.map((ink): [string, string] => [ink, surface]),
  ),
  // Ink on a filled control: buttons, the checkbox tick, the accent bar.
  ['--moh-accent-ink', '--moh-accent'],
  ['--moh-accent-ink', '--moh-accent-hover'],
  ['--moh-danger-ink', '--moh-danger'],
  ['--moh-danger-ink', '--moh-danger-hover'],
  // Status and error text, wherever a card or row puts it.
  ...[
    '--moh-parched',
    '--moh-sated',
    '--moh-frost',
    '--moh-thriving',
    '--moh-ailing',
    '--moh-danger',
  ].flatMap((tone): [string, string][] =>
    ['--moh-surface', '--moh-surface-raised', '--moh-surface-sunken', '--moh-selected'].map(
      (surface): [string, string] => [tone, surface],
    ),
  ),
];

/** Non-text: borders, focus rings and the filled parts of controls need 3:1. */
const NON_TEXT_PAIRS: [string, string][] = SURFACES.flatMap((surface): [string, string][] => [
  ['--moh-border', surface],
  ['--moh-gold-line', surface],
  ['--moh-accent', surface],
]);

describe.each(THEME_TOKENS)('%s theme', (name, theme) => {
  it.each(BODY_PAIRS)('%s on %s meets AA for body text', (ink, surface) => {
    expect(theme[ink], `${name} is missing ${ink}`).toBeDefined();
    expect(theme[surface], `${name} is missing ${surface}`).toBeDefined();
    expect(ratio(theme[ink], theme[surface])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT_PAIRS)('%s on %s meets AA for non-text', (fg, bg) => {
    expect(ratio(theme[fg], theme[bg])).toBeGreaterThanOrEqual(3);
  });

  it('defines every colour the light theme defines', () => {
    // Type, spacing and motion tokens are theme-independent and live in the
    // shared block; every colour has to exist in both themes.
    const missing = Object.keys(PARCHMENT).filter(
      (key) => !(key in theme) && /^(#|rgb)/i.test(PARCHMENT[key]),
    );
    expect(missing).toEqual([]);
  });
});

/* ---------------------------------------------------------------------------
 * What the components actually paint on what.
 * ------------------------------------------------------------------------- */

interface StyleRule {
  file: string;
  selector: string;
  body: string;
}

/** Walk a stylesheet's rules, descending into `@media` and friends. */
function eachRule(source: string, file: string, out: StyleRule[]): void {
  let depth = 0;
  let selectorStart = 0;
  let blockStart = 0;
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === '{') {
      if (depth === 0) blockStart = i;
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        const selector = source.slice(selectorStart, blockStart).trim();
        const body = source.slice(blockStart + 1, i);
        if (body.includes('{')) eachRule(body, file, out);
        else out.push({ file, selector, body });
        selectorStart = i + 1;
      }
    }
  }
}

interface Component {
  file: string;
  source: string;
  rules: StyleRule[];
}

const COMPONENTS: Component[] = readdirSync(here('.'))
  .filter((name) => name.endsWith('.svelte'))
  .sort()
  .map((name) => {
    const source = read(`./${name}`);
    const style = /<style[^>]*>([\s\S]*)<\/style>/.exec(source)?.[1] ?? '';
    const rules: StyleRule[] = [];
    eachRule(uncomment(style), name, rules);
    return { file: name, source, rules };
  });

/** The library's own stylesheets. `tokens.css` is excluded on purpose: it is
 *  where the tokens are declared, not where they are used. */
const CSS_FILES: { file: string; rules: StyleRule[] }[] = [{ file: 'base.css', rules: [] }];
eachRule(uncomment(baseCss), 'base.css', CSS_FILES[0].rules);

const FILL = /background(?:-color)?\s*:[^;]*var\((--moh-[\w-]+)\)/g;
const PLAIN_INK = /--moh-plain-ink\s*:\s*var\((--moh-[\w-]+)\)/g;

function matches(body: string, pattern: RegExp): string[] {
  return [...body.matchAll(new RegExp(pattern.source, 'g'))].map((match) => match[1]);
}

/** Fills that never have a paired label sitting on them, and why.
 *
 * A fill in this list is exempt from having to name its plain ink. A fill that
 * is in neither this list nor a rule that declares `--moh-plain-ink` fails the
 * test below: a new filled control has to say which of the two it is, which is
 * the whole point — nobody said it about the primary button, and nobody noticed
 * for three releases. */
const FILLS_WITHOUT_A_LABEL: Record<string, Record<string, string>> = {
  'Dialog.svelte': {
    '--moh-scrim': 'the backdrop; the panel above it carries its own surface',
  },
  'TaskCheckbox.svelte': {
    '--moh-accent': 'the tick box — it holds an svg stroke, never a label',
  },
  'Toggle.svelte': {
    '--moh-accent': 'the switch track; the label is outside the switch',
    '--moh-accent-ink': 'the knob',
    '--moh-ink-muted': 'the knob when off',
  },
};

describe('filled controls', () => {
  const offenders = COMPONENTS.filter(
    (component) => component.file === 'Label.svelte' || component.source.includes('<Label'),
  ).flatMap((component) => {
    const inks = new Set(component.rules.flatMap((rule) => matches(rule.body, PLAIN_INK)));
    const fills = new Set(component.rules.flatMap((rule) => matches(rule.body, FILL)));
    const exempt = FILLS_WITHOUT_A_LABEL[component.file] ?? {};
    const unmeasured = [...fills].filter(
      (token) => !SURFACES.includes(token) && !(token in exempt),
    );
    return unmeasured.length ? [{ file: component.file, inks: [...inks], fills: unmeasured }] : [];
  });

  it('is every component that paints a colour under a paired label', () => {
    // A guard on the guard: if this list empties out, the cases below stop
    // testing anything and nobody finds out.
    expect(offenders.map((entry) => entry.file)).toContain('Button.svelte');
  });

  it.each(offenders)('$file names the ink its plain half takes', ({ file, inks, fills }) => {
    expect(
      inks,
      `${file} fills ${fills.join(', ')} but never declares --moh-plain-ink. ` +
        'The plain half of its label keeps the page ink on a colour nobody measured. ' +
        'Declare --moh-plain-ink in the rule that sets the background, or add the ' +
        'fill to FILLS_WITHOUT_A_LABEL with the reason it carries no label.',
    ).not.toEqual([]);
  });

  const measured = offenders.flatMap(({ file, inks, fills }) =>
    inks.flatMap((ink) =>
      fills.flatMap((fill) =>
        THEME_TOKENS.map(([theme, values]) => ({ file, ink, fill, theme, values })),
      ),
    ),
  );

  it.each(measured)('$file: $ink on $fill meets AA in $theme', ({ ink, fill, values }) => {
    expect(ratio(values[ink], values[fill])).toBeGreaterThanOrEqual(4.5);
  });

  it('paints the plain half through --moh-plain-ink, not a hardcoded muted ink', () => {
    // The bug itself. `Label` is where every paired label in the app renders its
    // plain half, so this one declaration decided the contrast of every themed
    // button in the product.
    const label = COMPONENTS.find((component) => component.file === 'Label.svelte');
    const plain = label?.rules.find((rule) => rule.selector.trim() === '.plain');
    expect(plain?.body).toMatch(/color:\s*var\(--moh-plain-ink/);
  });

  it('measures what the shipped pairing actually was, so the number is on record', () => {
    // parchment: --moh-ink-muted on --moh-accent. greenhouse: the same pair.
    // Both are what a `themed` + `plain` primary button rendered before this fix.
    expect(ratio('#5c5142', '#2f4a36')).toBeCloseTo(1.26, 2);
    expect(ratio('#a9a695', '#7fb08a')).toBeCloseTo(1.01, 2);
  });
});

describe('full-strength antique gold', () => {
  // `--moh-gold-decor` fails AA on every light surface, so it is
  // decoration that carries no meaning. It may never be text, a border, a focus
  // ring or any other mark that is the sole indicator of state.
  const DECORATIVE_PROPERTIES = new Set([
    'background',
    'background-color',
    'background-image',
    'fill',
    'stroke',
  ]);

  it('is below AA on light, which is why it is decoration only', () => {
    for (const surface of SURFACES) {
      expect(ratio(PARCHMENT['--moh-gold-decor'], PARCHMENT[surface])).toBeLessThan(3);
    }
  });

  it('is never used for anything that carries meaning', () => {
    const used: string[] = [];
    for (const { file, rules } of [...COMPONENTS, ...CSS_FILES]) {
      for (const rule of rules) {
        for (const declaration of rule.body.split(';')) {
          if (!declaration.includes('--moh-gold-decor')) continue;
          const property = declaration.split(':')[0].trim();
          if (!DECORATIVE_PROPERTIES.has(property))
            used.push(`${file} ${rule.selector} ${property}`);
        }
      }
    }
    expect(used, 'a gold hairline may never be the only indicator of anything').toEqual([]);
  });
});

describe('the default theme', () => {
  // the design, question 3: a first-time visitor gets parchment whatever their
  // device prefers. The `@media (prefers-color-scheme: dark)` block that used to
  // hand a dark-mode phone the dark theme is gone, and stays gone.
  it('is not picked from the device by the stylesheet', () => {
    expect(uncomment(css)).not.toContain('prefers-color-scheme');
  });

  it('is parchment in theme.ts', () => {
    expect(DEFAULT_THEME_CHOICE).toBe('parchment');
  });

  it('is parchment in the pre-paint script too, with the device followed only on request', () => {
    // app.html runs before the stylesheet applies, so it is the only thing that
    // can still follow the device — and only for someone who stored "system".
    const script = appHtml.slice(appHtml.indexOf('<script>'), appHtml.indexOf('</script>'));
    expect(script).toContain("var theme = 'parchment'");
    expect(script).toContain("stored === 'system'");
    expect(script).toContain('prefers-color-scheme: dark');
  });

  it('paints the browser chrome the colour of the theme it starts in', () => {
    expect(appHtml).toContain(`content="${THEME_COLORS.parchment}"`);
  });
});

describe('theme.ts and the tokens agree', () => {
  it('knows the same themes the stylesheet defines', () => {
    for (const theme of THEMES) {
      expect(css).toContain(`[data-theme='${theme}']`);
    }
  });

  it('carries the same theme-colour as each theme surface', () => {
    expect(THEME_COLORS.parchment).toBe(PARCHMENT['--moh-surface']);
    expect(THEME_COLORS.greenhouse).toBe(GREENHOUSE['--moh-surface']);
  });

  it('shares its storage key with the pre-paint script in app.html', () => {
    // app.html applies the theme before the first paint; if the key or the
    // theme names drift apart, the page flashes the wrong theme on load.
    expect(appHtml).toContain(THEME_STORAGE_KEY);
    for (const theme of THEMES) expect(appHtml).toContain(theme);
    expect(appHtml).toContain(THEME_COLORS.greenhouse);
  });
});

describe('the display face', () => {
  // nothing may depend on a service the operator did not choose, and
  // the design names the consequence — the display face is self-hosted or absent.
  it('is served from this app and nowhere else', () => {
    expect(fontsCss).toContain("url('/fonts/cormorant-garamond-latin.woff2')");
    for (const sheet of [fontsCss, css, baseCss]) {
      expect(sheet).not.toMatch(/https?:\/\//);
      expect(sheet).not.toContain('fonts.googleapis.com');
      expect(sheet).not.toContain('fonts.gstatic.com');
    }
  });

  it('swaps rather than blocks, and keeps a system stack behind it', () => {
    expect(fontsCss).toContain('font-display: swap');
    // A heading falls back through installed serifs, never to a sans or a blank.
    expect(PARCHMENT['--moh-font-display']).toMatch(/serif\s*$/);
    expect(PARCHMENT['--moh-font-display']).toContain('Cormorant Garamond');
  });

  it('ships a utility sans for metadata, as a system stack', () => {
    expect(PARCHMENT['--moh-font-ui']).toContain('system-ui');
    expect(PARCHMENT['--moh-font-ui']).toMatch(/sans-serif\s*$/);
  });
});

describe('the token set itself', () => {
  it('measures every colour it claims to check', () => {
    for (const [name, theme] of THEME_TOKENS) {
      for (const pair of [...BODY_PAIRS, ...NON_TEXT_PAIRS].flat()) {
        expect(isOpaqueColour(theme[pair]), `${name} ${pair} is not a solid colour`).toBe(true);
      }
    }
  });

  it('keeps a touch target no smaller than 44px', () => {
    expect(PARCHMENT['--moh-tap']).toBe('44px');
    expect(parseInt(PARCHMENT['--moh-row'], 10)).toBeGreaterThanOrEqual(44);
  });

  it('keeps card corners inside the style guide’s 2–6px band', () => {
    expect(parseInt(PARCHMENT['--moh-radius'], 10)).toBeLessThanOrEqual(6);
    expect(parseInt(PARCHMENT['--moh-radius-lg'], 10)).toBeLessThanOrEqual(6);
  });

  it('keeps interactive feedback quick and ceremony for the atmosphere', () => {
    // the guide's 400–700ms is for page turns and plate reveals, not
    // for a checkbox taking a tap in the rain.
    expect(parseInt(PARCHMENT['--moh-motion-quick'], 10)).toBeLessThanOrEqual(200);
    expect(parseInt(PARCHMENT['--moh-motion-sheet'], 10)).toBeLessThanOrEqual(300);
    expect(parseInt(PARCHMENT['--moh-motion-atmospheric'], 10)).toBeGreaterThanOrEqual(400);
  });
});
