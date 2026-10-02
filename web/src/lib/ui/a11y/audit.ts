/** The accessibility audit — `npm run a11y`. The design system, an earlier release.
 *
 * The definition of done says the UI meets WCAG AA, and the earlier exit criterion is that this audit
 * passes. It drives Chromium over every route the app has, in both themes, at a
 * phone width and a tablet width, with `prefers-reduced-motion` both ways on the
 * busiest route, and runs axe-core on each. Any `serious` or `critical`
 * violation of a WCAG rule fails the run. Everything it finds, `moderate`
 * included, is printed per route and per theme with the rule id and the first
 * offending selector, so whoever owns the route can go straight to it.
 *
 * Node runs this file directly — no build step, no test runner. It needs:
 *
 *   1. the API, in mock mode, already listening on `MOH_API_URL`
 *      (default http://127.0.0.1:8000). From the repository root:
 *
 *          PYTHONPATH=api:. MOH_MOCK_MODE=true \
 *            .venv/bin/uvicorn app.main:app --port 8000
 *
 *   2. a production build of the web app (`npm run build`). The audit starts
 *      `build/index.js` itself, puts a small proxy in front of it that sends
 *      `/api/` to the API and everything else to the app — the same split the
 *      deployment's Nginx makes — and audits through the proxy, so server-side
 *      `load` functions reach the API exactly as they do in production.
 *
 * Set `MOH_A11Y_URL` to audit an app that is already running (a `vite dev`
 * server with its proxy, or a deployment) instead; nothing is started then.
 *
 * Chromium: Playwright's own download is used when it is there. On a machine
 * that ships a Chromium elsewhere — this project's CI image puts one at
 * `/opt/pw-browsers/chromium` — point `MOH_A11Y_CHROMIUM` at the executable.
 * Never run `playwright install` here.
 *
 * `MOH_A11Y_REPORT=path.md` also writes the tables as Markdown, for a pull
 * request body or a releases note. `MOH_A11Y_ONLY=/journal` audits only the
 * routes whose path contains that text, for iterating on one screen.
 *
 * The route list is `AUDIT_ROUTES` below, exported so the test suite's end-to-end
 * suite can walk the same list. Importing this module runs nothing; the
 * audit starts only when the file is the script Node was given.
 */

import AxeBuilder from '@axe-core/playwright';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
import { createServer, request as httpRequest, type Server } from 'node:http';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium, type Browser, type BrowserContext } from 'playwright';

// ----------------------------------------------------------------- the list

/** The fixture specimen every per-specimen route is audited with. It is the
 *  first entry in `fixtures/specimens/specimens.json`; override it with
 *  `MOH_SPECIMEN_ID` to audit against a different one. */
export const DEFAULT_SPECIMEN_ID = '01890040-0000-7000-8000-000000000001';

export interface AuditRoute {
  /** The path, with the specimen id already in it. */
  path: string;
  /** The screen's name as the plan calls it. */
  name: string;
  /** Who owns the files that render it, so a finding has an address. */
  owner: 'H' | 'I' | 'J' | 'K';
  /** Anything the reader of the table should know about this route. */
  note?: string;
}

/** Every route the app has. In one place, on purpose: L reuses it and
 *  The deployment runs it in CI, and a route that is not in this list is not audited.
 *
 *  `/register` and `/office` are in the plan and in the navigation bar but have
 *  no `+page.svelte` yet, so what is audited at those paths is the error page.
 *  They stay in the list so the day they are built they are audited without
 *  anybody remembering to add them. */
export function auditRoutes(specimenId: string = DEFAULT_SPECIMEN_ID): AuditRoute[] {
  return [
    { path: '/', name: 'Morning Rounds', owner: 'J' },
    { path: '/register', name: 'The Register', owner: 'J', note: 'not built yet: error page' },
    { path: '/grounds', name: 'The Grounds', owner: 'H' },
    { path: '/almanac', name: 'The Almanac', owner: 'J' },
    { path: '/almanac/today', name: 'The Almanac — today', owner: 'J' },
    { path: '/almanac/history', name: 'The Almanac — history', owner: 'J' },
    { path: '/office', name: 'Ministry Office', owner: 'J', note: 'not built yet: error page' },
    { path: `/specimen/${specimenId}/register`, name: 'Specimen — register facet', owner: 'J' },
    { path: `/specimen/${specimenId}/tending`, name: 'Specimen — tending facet', owner: 'J' },
    {
      path: `/specimen/${specimenId}/compendium`,
      name: 'Specimen — compendium facet',
      owner: 'J',
    },
    { path: `/specimen/${specimenId}/journal`, name: 'Specimen — journal facet', owner: 'J' },
    { path: '/journal', name: "The Naturalist's Journal", owner: 'K' },
    { path: `/journal/${specimenId}`, name: 'Journal — one plant', owner: 'K' },
    { path: '/gallery', name: 'Component gallery', owner: 'I' },
    { path: '/no-such-page', name: 'Error page', owner: 'J', note: 'deliberate 404' },
  ];
}

export const AUDIT_ROUTES: AuditRoute[] = auditRoutes(
  process.env.MOH_SPECIMEN_ID || DEFAULT_SPECIMEN_ID,
);

export const AUDIT_THEMES = ['parchment', 'greenhouse'] as const;
export type AuditTheme = (typeof AUDIT_THEMES)[number];

export const AUDIT_VIEWPORTS = [
  { name: '375×812', width: 375, height: 812 },
  { name: '1024×768', width: 1024, height: 768 },
] as const;

/** The route that is also audited with `prefers-reduced-motion: reduce`. Morning
 *  Rounds, because it is the one with the most motion in it (the tick that
 *  draws itself, the card that settles) and the one used most. */
export const REDUCED_MOTION_ROUTE = '/';

// ------------------------------------------------------------------ results

export type Impact = 'critical' | 'serious' | 'moderate' | 'minor';
const IMPACTS: Impact[] = ['critical', 'serious', 'moderate', 'minor'];

export interface Finding {
  rule: string;
  impact: Impact;
  /** True when the rule carries a WCAG 2.x A or AA tag; a best-practice rule
   *  is reported but never fails the run. */
  wcag: boolean;
  help: string;
  helpUrl: string;
  /** The first offending selector, and how many nodes in all. */
  selector: string;
  nodes: number;
}

export interface Pass {
  route: AuditRoute;
  theme: AuditTheme;
  viewport: string;
  motion: 'no-preference' | 'reduce';
  status: number;
  findings: Finding[];
  incomplete: number;
}

/** What makes the run fail: a WCAG rule, broken seriously or worse. */
export function blocking(finding: Finding): boolean {
  return finding.wcag && (finding.impact === 'critical' || finding.impact === 'serious');
}

const WCAG_TAG = /^wcag2(1|2)?aa?$/;

// -------------------------------------------------------------- the servers

const API_URL = process.env.MOH_API_URL || 'http://127.0.0.1:8000';

export interface Stack {
  origin: string;
  stop(): Promise<void>;
}

async function waitFor(url: string, what: string, tries = 60): Promise<void> {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // not up yet
    }
    await new Promise((done) => setTimeout(done, 500));
  }
  throw new Error(`${what} did not answer at ${url}`);
}

interface Health {
  status?: string;
  mode?: string;
  contract_version?: string;
}

async function requireApi(): Promise<void> {
  const health = `${API_URL}/api/v1/healthz`;
  let body: Health | null = null;
  try {
    body = (await (await fetch(health)).json()) as Health;
  } catch {
    // reported below
  }
  if (!body || body.status !== 'ok') {
    throw new Error(
      `No API at ${API_URL}. Start it from the repository root in mock mode:\n\n` +
        '    PYTHONPATH=api:. MOH_MOCK_MODE=true .venv/bin/uvicorn app.main:app --port 8000\n\n' +
        'or point MOH_API_URL at one that is running.',
    );
  }
  console.log(`API ${API_URL}: ${body.mode} mode, contract ${body.contract_version}`);
}

/** A port the kernel says is free right now. */
export function freePort(): Promise<number> {
  return new Promise((done, fail) => {
    const probe = createServer();
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      probe.close(() => (port ? done(port) : fail(new Error('no free port'))));
    });
  });
}

/** The deployment's Nginx split, in forty lines: `/api/` goes to the API and
 *  everything else to the app, on one origin. */
function startProxy(port: number, apiBase: URL, webBase: URL): Promise<Server> {
  const server = createServer((req, res) => {
    const target = req.url?.startsWith('/api/') ? apiBase : webBase;
    const upstream = httpRequest(
      {
        hostname: target.hostname,
        port: target.port,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: `${target.hostname}:${target.port}` },
      },
      (answer) => {
        res.writeHead(answer.statusCode ?? 502, answer.headers);
        answer.pipe(res);
      },
    );
    upstream.on('error', (error) => {
      res.writeHead(502, { 'content-type': 'text/plain' });
      res.end(`proxy: ${error.message}`);
    });
    req.pipe(upstream);
  });
  return new Promise((done) => server.listen(port, '127.0.0.1', () => done(server)));
}

/** Which ports to use, for a caller that has to stop the stack and bring it
 *  back on the same origin — the offline check does, because a browser's
 *  caches belong to an origin and a new port is a new origin. */
export interface StackPorts {
  web: number;
  proxy: number;
}

export async function startStack(ports?: StackPorts): Promise<Stack> {
  if (process.env.MOH_A11Y_URL) {
    const origin = process.env.MOH_A11Y_URL.replace(/\/$/, '');
    await waitFor(`${origin}/gallery`, 'the app');
    console.log(`Auditing the app already running at ${origin}`);
    return { origin, stop: async () => {} };
  }

  await requireApi();
  const entry = resolve('build/index.js');
  if (!existsSync(entry)) {
    throw new Error(`No production build at ${entry}. Run \`npm run build\` first.`);
  }

  const webPort = ports?.web ?? (await freePort());
  const proxyPort = ports?.proxy ?? (await freePort());
  const origin = `http://127.0.0.1:${proxyPort}`;

  const web: ChildProcess = spawn(process.execPath, [entry], {
    env: { ...process.env, PORT: String(webPort), HOST: '127.0.0.1', ORIGIN: origin },
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  const proxy = await startProxy(
    proxyPort,
    new URL(API_URL),
    new URL(`http://127.0.0.1:${webPort}`),
  );
  await waitFor(`${origin}/gallery`, 'the web app');
  console.log(`Web app ${origin} → build/index.js on :${webPort}, /api/ → ${API_URL}`);

  return {
    origin,
    stop: () =>
      new Promise((done) => {
        web.kill();
        proxy.close(() => done());
      }),
  };
}

// -------------------------------------------------------------- the browser

async function openBrowser(): Promise<Browser> {
  const executablePath = process.env.MOH_A11Y_CHROMIUM;
  return chromium.launch(executablePath ? { executablePath } : {});
}

async function audit(
  browser: Browser,
  origin: string,
  route: AuditRoute,
  theme: AuditTheme,
  viewport: (typeof AUDIT_VIEWPORTS)[number],
  motion: Pass['motion'],
): Promise<Pass> {
  const context: BrowserContext = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: motion,
    // A phone-sized viewport that is also a touch device, so hover-only
    // affordances do not pass by accident.
    hasTouch: viewport.width < 600,
  });
  // The theme is a stored choice, read by app.html before first paint.
  await context.addInitScript((choice: string) => {
    window.localStorage.setItem('moh-theme', choice);
  }, theme);

  const page = await context.newPage();
  const response = await page.goto(`${origin}${route.path}`, { waitUntil: 'networkidle' });
  await page.waitForFunction(
    (expected: string) => document.documentElement.dataset.theme === expected,
    theme,
  );
  // Fonts swap in and the live regions settle; axe measures what is painted.
  await page.waitForTimeout(250);

  const results = await new AxeBuilder({ page }).analyze();
  await context.close();

  const findings: Finding[] = results.violations.map((violation) => ({
    rule: violation.id,
    impact: (violation.impact ?? 'minor') as Impact,
    wcag: violation.tags.some((tag) => WCAG_TAG.test(tag)),
    help: violation.help,
    helpUrl: violation.helpUrl,
    selector: violation.nodes[0]?.target.map(String).join(' ') ?? '',
    nodes: violation.nodes.length,
  }));
  findings.sort((a, b) => IMPACTS.indexOf(a.impact) - IMPACTS.indexOf(b.impact));

  return {
    route,
    theme,
    viewport: viewport.name,
    motion,
    status: response?.status() ?? 0,
    findings,
    incomplete: results.incomplete.length,
  };
}

// --------------------------------------------------------------- reporting

function count(findings: Finding[], impact: Impact): number {
  return findings.filter((finding) => finding.impact === impact).length;
}

function table(rows: string[][], header: string[]): string {
  const widths = header.map((_, column) =>
    Math.max(header[column].length, ...rows.map((row) => row[column].length)),
  );
  const line = (row: string[]) =>
    `| ${row.map((cell, column) => cell.padEnd(widths[column])).join(' | ')} |`;
  return [line(header), `| ${widths.map((w) => '-'.repeat(w)).join(' | ')} |`, ...rows.map(line)]
    .join('\n')
    .concat('\n');
}

export function summaryTable(passes: Pass[]): string {
  const rows = passes.map((pass) => [
    pass.route.path,
    pass.route.owner,
    pass.theme,
    pass.viewport,
    pass.motion === 'reduce' ? 'reduce' : '',
    String(pass.status),
    String(count(pass.findings, 'critical')),
    String(count(pass.findings, 'serious')),
    String(count(pass.findings, 'moderate')),
    String(count(pass.findings, 'minor')),
    String(pass.incomplete),
  ]);
  return table(rows, [
    'route',
    'owner',
    'theme',
    'viewport',
    'motion',
    'http',
    'critical',
    'serious',
    'moderate',
    'minor',
    'incomplete',
  ]);
}

/** One line per distinct (route, rule, selector), saying where it was seen. */
export function findingsTable(passes: Pass[]): string {
  const seen = new Map<string, { finding: Finding; route: AuditRoute; where: Set<string> }>();
  for (const pass of passes) {
    for (const finding of pass.findings) {
      const key = `${pass.route.path}\u0000${finding.rule}\u0000${finding.selector}`;
      const entry = seen.get(key) ?? { finding, route: pass.route, where: new Set<string>() };
      entry.where.add(`${pass.theme} ${pass.viewport}${pass.motion === 'reduce' ? ' rm' : ''}`);
      seen.set(key, entry);
    }
  }
  const rows = [...seen.values()]
    .sort(
      (a, b) =>
        IMPACTS.indexOf(a.finding.impact) - IMPACTS.indexOf(b.finding.impact) ||
        a.route.path.localeCompare(b.route.path),
    )
    .map(({ finding, route, where }) => [
      blocking(finding) ? 'FAIL' : finding.wcag ? 'wcag' : 'best-practice',
      finding.impact,
      route.path,
      route.owner,
      finding.rule,
      `\`${finding.selector}\`${finding.nodes > 1 ? ` (+${finding.nodes - 1})` : ''}`,
      [...where].join(', '),
    ]);
  if (!rows.length) return 'No violations.\n';
  return table(rows, ['', 'impact', 'route', 'owner', 'rule', 'first selector', 'seen in']);
}

function helpTable(passes: Pass[]): string {
  const rules = new Map<string, Finding>();
  for (const pass of passes) for (const finding of pass.findings) rules.set(finding.rule, finding);
  const rows = [...rules.values()]
    .sort((a, b) => a.rule.localeCompare(b.rule))
    .map((finding) => [finding.rule, finding.help, finding.helpUrl]);
  return rows.length ? table(rows, ['rule', 'what it means', 'reference']) : '';
}

// --------------------------------------------------------------------- main

export async function run(): Promise<number> {
  const stack = await startStack();
  const browser = await openBrowser();
  const passes: Pass[] = [];
  const started = Date.now();
  const only = process.env.MOH_A11Y_ONLY;
  const routes = only ? AUDIT_ROUTES.filter((route) => route.path.includes(only)) : AUDIT_ROUTES;
  if (!routes.length) throw new Error(`MOH_A11Y_ONLY=${only} matches no route in AUDIT_ROUTES`);

  try {
    for (const route of routes) {
      for (const theme of AUDIT_THEMES) {
        for (const viewport of AUDIT_VIEWPORTS) {
          passes.push(await audit(browser, stack.origin, route, theme, viewport, 'no-preference'));
        }
        if (route.path === REDUCED_MOTION_ROUTE) {
          passes.push(
            await audit(browser, stack.origin, route, theme, AUDIT_VIEWPORTS[0], 'reduce'),
          );
        }
      }
      const found = passes
        .filter((pass) => pass.route === route)
        .reduce((sum, pass) => sum + pass.findings.length, 0);
      console.log(`  ${route.path.padEnd(60)} ${found ? `${found} finding(s)` : 'clean'}`);
    }
  } finally {
    await browser.close();
    await stack.stop();
  }

  const failures = passes.flatMap((pass) => pass.findings.filter(blocking));
  const seconds = ((Date.now() - started) / 1000).toFixed(0);
  const report =
    `## Accessibility audit\n\n` +
    `${passes.length} page loads over ${routes.length} of ${AUDIT_ROUTES.length} routes, both themes, ` +
    `${AUDIT_VIEWPORTS.map((v) => v.name).join(' and ')}, in ${seconds}s. ` +
    `Fails on a serious or critical WCAG violation; best-practice rules are listed, not counted.\n\n` +
    `### Per route and theme\n\n${summaryTable(passes)}\n` +
    `### Every finding\n\n${findingsTable(passes)}\n` +
    (helpTable(passes) ? `### The rules\n\n${helpTable(passes)}\n` : '') +
    `**Result: ${failures.length ? `FAIL — ${failures.length} blocking` : 'PASS'}.**\n`;

  console.log(`\n${report}`);
  if (process.env.MOH_A11Y_REPORT) {
    writeFileSync(process.env.MOH_A11Y_REPORT, report);
    console.log(`Written to ${process.env.MOH_A11Y_REPORT}`);
  }
  return failures.length ? 1 : 0;
}

const invokedDirectly =
  typeof process.argv[1] === 'string' && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  run().then(
    (code) => process.exit(code),
    (error: unknown) => {
      console.error(error instanceof Error ? error.message : error);
      process.exit(2);
    },
  );
}
