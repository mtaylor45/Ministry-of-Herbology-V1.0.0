/** The Almanac's own suite.
 *
 * Rendered through `svelte/server`, the way the design system's library is tested,
 * so the screens are checked without adding a DOM emulator to a `package.json`
 * this parts of the project does not own. The arithmetic and the wording are pure
 * functions and are tested directly.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import Caveats from '../shared/Caveats.svelte';
import Chart from './Chart.svelte';
import DayRow from './DayRow.svelte';
import SiteMissing from './SiteMissing.svelte';
import { indoorLocations, siteIdFrom, type ForecastPoint, type Series } from './api';
import {
  CONFIDENCE_ORDER,
  capSentence,
  caveatSummary,
  caveats,
  isDegraded,
  measurementConfidence,
  reportsItsOwnConfidence,
  weakest,
} from '../shared/assessment';
import {
  FROST_MARGIN_C,
  addDays,
  conditionLabel,
  dailyRows,
  dayLabel,
  dayOf,
  daySentence,
  formatPrecip,
  formatProbability,
  formatTemp,
  freezingPct,
  frostNights,
  frostRisk,
  hourlyExtremes,
  hourlyRows,
  rainSentence,
  rangeBar,
  temperatureDomain,
  totalPrecip,
} from './forecast';
import {
  METRICS,
  align,
  bucketLabel,
  columns,
  hasAnyValue,
  indoorGap,
  indoorIsReal,
  metricsFor,
  parseMetric,
  parseWindow,
  summary,
} from './history';

const SITE = '01890000-0000-7000-8000-000000000001';

/** A daily row exactly as `api/almanac/service.py` serves one. */
function daily(overrides: Partial<ForecastPoint> = {}): ForecastPoint {
  return {
    time: '2026-05-01T00:00:00Z',
    temp_min_c: 13,
    temp_max_c: 22,
    temperature_c: null,
    precip_mm: 0,
    precip_prob_pct: 10,
    et0_mm: 3.6,
    wind_kph: 12,
    condition: 'partly_cloudy',
    sunrise: '2026-05-01T11:00:00Z',
    sunset: '2026-05-02T01:00:00Z',
    ...overrides,
  };
}

function hourly(hour: number, overrides: Partial<ForecastPoint> = {}): ForecastPoint {
  return {
    time: `2026-05-01T${String(hour).padStart(2, '0')}:00:00Z`,
    temperature_c: 15,
    temp_min_c: null,
    temp_max_c: null,
    precip_mm: 0,
    precip_prob_pct: 10,
    et0_mm: null,
    wind_kph: 12,
    condition: 'partly_cloudy',
    sunrise: null,
    sunset: null,
    ...overrides,
  };
}

function series(overrides: Partial<Series> = {}): Series {
  return {
    metric: 'temperature_c',
    unit: '°C',
    times: [1779580800, 1779667200, 1779753600],
    values: [15.5, 16.4, 17.4],
    min: [11, 11.9, 12.9],
    max: [20, 20.9, 21.9],
    label: 'temperature_c · last 7d',
    source: 'weather_daily',
    ...overrides,
  };
}

// --------------------------------------------------------------- the calendar

describe('the day a forecast row is about', () => {
  it('reads the date off the stamp rather than through the reader s clock', () => {
    // Daily rows are stamped midnight UTC of the site's own day. Converting
    // them would move every one of them to the day before for anybody west of
    // Greenwich, and the ten-day strip would open on yesterday.
    expect(dayOf(daily())).toBe('2026-05-01');
    expect(dayOf(daily({ time: '2026-10-23T00:00:00Z' }))).toBe('2026-10-23');
  });

  it('names today and tomorrow, and dates everything else', () => {
    expect(dayLabel('2026-05-01', { today: '2026-05-01' })).toBe('Today');
    expect(dayLabel('2026-05-02', { today: '2026-05-01' })).toBe('Tomorrow');
    expect(dayLabel('2026-05-08', { today: '2026-05-01', locale: 'en-GB' })).toMatch(/8 May/);
  });

  it('counts days across a month boundary', () => {
    expect(addDays('2026-05-31', 1)).toBe('2026-06-01');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
  });
});

// ------------------------------------------------------------------ the frost

describe('frost, read off the forecast s own lows', () => {
  it('keeps the guard s 3 °F margin', () => {
    expect(FROST_MARGIN_C).toBeCloseTo(1.667, 3);
  });

  it('calls freezing a frost and the margin above it a cold night', () => {
    expect(frostRisk(-2)).toBe('frost');
    expect(frostRisk(0)).toBe('frost');
    expect(frostRisk(1.5)).toBe('near');
    expect(frostRisk(2)).toBeNull();
    expect(frostRisk(13)).toBeNull();
  });

  it('says nothing at all about a night with no low', () => {
    expect(frostRisk(null)).toBeNull();
    expect(frostRisk(undefined)).toBeNull();
  });

  it('picks the cold nights out of a run of days', () => {
    const rows = dailyRows([
      daily({ time: '2026-10-22T00:00:00Z', temp_min_c: 4 }),
      daily({ time: '2026-10-23T00:00:00Z', temp_min_c: -2 }),
      daily({ time: '2026-10-24T00:00:00Z', temp_min_c: 1 }),
    ]);
    expect(frostNights(rows).map((row) => row.day)).toEqual(['2026-10-23', '2026-10-24']);
  });
});

// ------------------------------------------------------------------ the scale

describe('the temperature scale the strip is drawn against', () => {
  it('is the week s own, not stretched to reach a freezing nothing is near', () => {
    const rows = dailyRows([daily({ temp_min_c: 13, temp_max_c: 22 })]);
    expect(temperatureDomain(rows)).toEqual({ min: 12, max: 23 });
    expect(freezingPct(temperatureDomain(rows))).toBeNull();
  });

  it('marks freezing when the week actually reaches it', () => {
    const rows = dailyRows([
      daily({ temp_min_c: -3, temp_max_c: 9 }),
      daily({ time: '2026-10-24T00:00:00Z', temp_min_c: 2, temp_max_c: 11 }),
    ]);
    const at = freezingPct(temperatureDomain(rows));
    expect(at).not.toBeNull();
    expect(at).toBeGreaterThan(1);
    expect(at).toBeLessThan(99);
  });

  it('never returns a domain of zero width', () => {
    const rows = dailyRows([daily({ temp_min_c: 10, temp_max_c: 10 })]);
    const domain = temperatureDomain(rows);
    expect(domain.max).toBeGreaterThan(domain.min);
  });

  it('draws no bar for a day missing either end of its range', () => {
    const [row] = dailyRows([daily({ temp_max_c: null })]);
    expect(rangeBar(row, { min: 0, max: 30 })).toBeNull();
  });

  it('keeps a bar inside its track and wide enough to see', () => {
    const [row] = dailyRows([daily({ temp_min_c: 20, temp_max_c: 20 })]);
    const bar = rangeBar(row, { min: 0, max: 30 });
    expect(bar).not.toBeNull();
    expect(bar!.startPct).toBeGreaterThanOrEqual(0);
    expect(bar!.lengthPct).toBeGreaterThanOrEqual(2);
    expect(bar!.startPct + bar!.lengthPct).toBeLessThanOrEqual(100);
  });
});

// ----------------------------------------------------------------- the wording

describe('what the numbers read as', () => {
  it('says a temperature is not forecast rather than showing a blank', () => {
    expect(formatTemp(13.04)).toBe('13 °C');
    expect(formatTemp(null)).toBe('not forecast');
  });

  it('distinguishes no rain from no forecast of rain', () => {
    expect(formatPrecip(0)).toBe('none');
    expect(formatPrecip(6)).toBe('6 mm');
    expect(formatPrecip(null)).toBe('not forecast');
  });

  it('leaves the probability out rather than inventing one', () => {
    expect(formatProbability(80)).toBe('80% chance');
    expect(formatProbability(null)).toBeNull();
  });

  it('never phrases rain so that the chance contradicts the amount', () => {
    // "Rain none, 10% chance" reads as a 10% chance of no rain.
    expect(rainSentence({ precipMm: 0, precipProbPct: 10 })).toBe('No rain, 10% chance of any');
    expect(rainSentence({ precipMm: 6, precipProbPct: 80 })).toBe('Rain 6 mm, 80% chance');
    expect(rainSentence({ precipMm: 6, precipProbPct: null })).toBe('Rain 6 mm');
    expect(rainSentence({ precipMm: null, precipProbPct: null })).toBe('Rain not forecast');
  });

  it('reads a cold day as one sentence with the frost in it', () => {
    const [row] = dailyRows([daily({ temp_min_c: -2, temp_max_c: 9, precip_mm: 0 })], {
      today: '2026-05-01',
    });
    const sentence = daySentence(row);
    expect(sentence).toContain('high 9 °C');
    expect(sentence).toContain('low -2 °C');
    expect(sentence).toContain('no rain');
    expect(sentence).toMatch(/freezing/i);
  });

  it('names every condition the sources normalise to', () => {
    for (const code of ['clear', 'partly_cloudy', 'cloudy', 'rain', 'snow', 'storm', 'fog']) {
      const label = conditionLabel(code);
      expect(label?.plain.trim()).not.toBe('');
      expect(label?.themed.trim()).not.toBe('');
    }
    // An unknown code is shown, not swallowed.
    expect(conditionLabel('hail_of_frogs')?.plain).toBe('Hail of frogs');
    expect(conditionLabel(null)).toBeNull();
  });
});

// -------------------------------------------------------------------- the day

describe('the hourly trace', () => {
  const rows = hourlyRows(
    [hourly(0, { temperature_c: 12 }), hourly(14, { temperature_c: 22, precip_mm: 1.5 })],
    { timeZone: 'UTC', locale: 'en-GB' },
  );

  it('plots unix seconds, which is what uPlot reads', () => {
    expect(rows[0].at).toBe(Date.parse('2026-05-01T00:00:00Z') / 1000);
  });

  it('reads the day s extremes off the trace rather than asking twice', () => {
    expect(hourlyExtremes(rows)).toEqual({ low: 12, high: 22 });
  });

  it('totals the rain without floating-point crumbs', () => {
    expect(totalPrecip([{ precipMm: 1.5 }, { precipMm: 1.2 }, { precipMm: null }])).toBe(2.7);
  });

  it('has no extremes to report when nothing was forecast', () => {
    expect(hourlyExtremes([])).toEqual({ low: null, high: null });
  });
});

// ------------------------------------------------------------- confidence

describe('confidence, and the reasons it is not higher', () => {
  const stale = {
    code: 'ingest_stale',
    detail: 'The newest stored reading is 30 hours old.',
    caps_at: 'low' as const,
  };
  const fallback = {
    code: 'et0_fallback',
    detail: 'ET₀ was computed locally (Hargreaves) for 2 days.',
    caps_at: 'medium' as const,
  };

  it('knows the difference between a clean answer and a silent one', () => {
    expect(reportsItsOwnConfidence(null)).toBe(false);
    expect(reportsItsOwnConfidence({})).toBe(false);
    expect(reportsItsOwnConfidence({ confidence: 'high' })).toBe(true);
    expect(reportsItsOwnConfidence({ degraded: false })).toBe(true);
  });

  it('puts the worst ceiling first, because that is the one that decides', () => {
    expect(caveats({ degradations: [fallback, stale] }).map((d) => d.code)).toEqual([
      'ingest_stale',
      'et0_fallback',
    ]);
  });

  it('treats an answer with reasons as degraded even if it forgot to say so', () => {
    expect(isDegraded({ degradations: [stale] })).toBe(true);
    expect(isDegraded({ confidence: 'high', degradations: [] })).toBe(false);
  });

  it('counts the reasons for the collapsed summary', () => {
    expect(caveatSummary({ degradations: [stale] })).toMatch(/1 reason/);
    expect(caveatSummary({ degradations: [stale, fallback] })).toMatch(/2 reasons/);
    expect(caveatSummary({})).toBe('');
  });

  it('pairs a themed word with a plain one at every level', () => {
    for (const level of CONFIDENCE_ORDER) {
      const status = measurementConfidence(level);
      expect(status.themed.trim()).not.toBe('');
      expect(status.plain.trim()).not.toBe('');
      expect(status.themed).not.toBe(status.plain);
    }
  });

  it('does not read silence as high confidence', () => {
    expect(measurementConfidence(undefined).plain).toMatch(/does not say/i);
    expect(measurementConfidence(undefined).tone).not.toBe('thriving');
  });

  it('states the ceiling a reason puts on the answer', () => {
    expect(capSentence(stale)).toMatch(/low confidence/i);
  });

  it('is worth its weakest link across panels', () => {
    expect(weakest({ confidence: 'high' }, { confidence: 'low' })).toBe('low');
    expect(weakest({}, {})).toBeUndefined();
  });
});

// ---------------------------------------------------------------- the record

describe('history, indoors against outdoors', () => {
  it('refuses to call the site s own weather an indoor reading', () => {
    // This is what the API actually answers a location query with today.
    expect(indoorIsReal(series({ source: 'weather_daily' }))).toBe(false);
    expect(indoorIsReal(series({ source: 'reading_daily' }))).toBe(true);
  });

  it('treats an all-empty series as no reading rather than as a flat line', () => {
    expect(hasAnyValue(series({ values: [null, null, null] }))).toBe(false);
    expect(indoorIsReal(series({ source: 'reading_daily', values: [null, null, null] }))).toBe(
      false,
    );
  });

  it('says why the indoor line is missing, in each of the three ways it can be', () => {
    expect(indoorGap(series({ source: 'weather_daily' }), 'temperature_c')).toMatch(
      /outdoor weather/i,
    );
    expect(
      indoorGap(series({ source: 'reading_daily', values: [null] }), 'soil_moisture_pct'),
    ).toMatch(/soil moisture/i);
    expect(indoorGap(series({ source: 'reading_daily', values: [null] }), 'humidity_pct')).toMatch(
      /no indoor readings/i,
    );
    expect(indoorGap(series({ source: 'reading_daily' }), 'temperature_c')).toBeNull();
  });

  it('offers only the questions a place can answer', () => {
    expect(metricsFor('site')).not.toContain('soil_moisture_pct');
    expect(metricsFor('indoor')).not.toContain('precip_mm');
    expect(metricsFor('indoor')).not.toContain('et0_mm');
  });

  it('aligns two series on the union of their days, leaving gaps as gaps', () => {
    const outdoor = series({ times: [1, 2, 3], values: [10, 11, 12], min: [], max: [] });
    const indoor = series({ times: [2, 3, 4], values: [20, 21, 22], source: 'reading_daily' });
    const rows = align(outdoor, indoor);
    expect(rows.map((row) => row.at)).toEqual([1, 2, 3, 4]);
    expect(rows[0].indoor).toBeNull();
    expect(rows[3].outdoor).toBeNull();
    expect(rows[1]).toMatchObject({ outdoor: 11, indoor: 20 });
  });

  it('hands uPlot columns, and only the indoor one when there is an indoor one', () => {
    const rows = align(series({ times: [1, 2], values: [10, 11] }), null);
    expect(columns(rows, { range: false, indoor: false })).toEqual([
      [1, 2],
      [10, 11],
    ]);
    expect(columns(rows, { range: false, indoor: true })).toHaveLength(3);
  });

  it('summarises the range in words, for anyone not reading the chart', () => {
    const rows = align(series({ times: [1, 2], values: [10, 20] }), null);
    expect(summary(rows, 'temperature_c', { range: false, indoor: false })).toBe(
      'Outdoors ranged from 10 °C to 20 °C.',
    );
    expect(summary([], 'temperature_c', { range: false, indoor: false })).toMatch(
      /Nothing has been recorded/,
    );
  });

  it('labels a bucket by its own day, in UTC, as the rollup stores it', () => {
    expect(bucketLabel(Date.parse('2026-05-24T00:00:00Z') / 1000, 'en-GB')).toMatch(/24 May/);
  });

  it('pairs a themed name with a plain one for every metric', () => {
    for (const metric of Object.values(METRICS)) {
      expect(metric.plain.trim()).not.toBe('');
      expect(metric.themed).not.toBe(metric.plain);
    }
  });

  it('takes nothing from the query string on trust', () => {
    expect(parseWindow('7d')).toBe('7d');
    expect(parseWindow('90d')).toBe('7d');
    expect(parseWindow(null)).toBe('7d');
    expect(parseMetric('precip_mm')).toBe('precip_mm');
    expect(parseMetric('../../etc/passwd')).toBe('temperature_c');
  });
});

// ------------------------------------------------------------------ the site

describe('finding the site the Almanac is about', () => {
  const locations = [
    { id: 'a', name: 'Study', kind: 'room', is_outdoor: false },
    { id: 'b', name: 'Front Bed', kind: 'bed', is_outdoor: true, site_id: SITE },
  ];

  it('reads it off a location, since the contract lists no sites', () => {
    expect(siteIdFrom(locations)).toBe(SITE);
    expect(siteIdFrom([locations[0]])).toBeNull();
    expect(siteIdFrom([])).toBeNull();
  });

  it('offers the indoor rooms for the comparison', () => {
    expect(indoorLocations(locations).map((l) => l.id)).toEqual(['a']);
  });
});

// ------------------------------------------------------------- what renders

describe('the screens, rendered', () => {
  it('shows a degradation in the engine s own words, in full', () => {
    const detail =
      'ET₀ was computed locally (Hargreaves) for 2 days, because the forecast did not carry it.';
    const markup = html(Caveats, {
      what: 'This forecast',
      payload: {
        confidence: 'medium',
        degraded: true,
        degradations: [{ code: 'et0_fallback', detail, caps_at: 'medium' }],
      },
    });
    // Verbatim: The weather engine writes these sentences to be shown as they stand.
    expect(text(markup)).toContain(detail);
    expect(text(markup)).toMatch(/medium confidence/i);
  });

  it('says plainly when an endpoint reports no confidence at all', () => {
    const markup = text(html(Caveats, { what: 'This forecast', payload: null }));
    expect(markup).toMatch(/does not say how sure it is/i);
    expect(markup).toMatch(/clean bill of health/i);
  });

  it('can be told to keep quiet where a notice would be noise', () => {
    const markup = html(Caveats, {
      what: 'This forecast',
      payload: null,
      noticeWhenSilent: false,
    });
    expect(text(markup)).toBe('');
  });

  it('carries every figure in a day row as text, not only as a bar', () => {
    const [row] = dailyRows([
      daily({ temp_min_c: -2, temp_max_c: 9, precip_mm: 6, precip_prob_pct: 80 }),
    ]);
    const markup = html(DayRow, { row, domain: { min: -3, max: 10 }, freezingAt: 20 });
    const read = text(markup);
    expect(read).toContain('-2 °C');
    expect(read).toContain('9 °C');
    expect(read).toContain('Rain 6 mm, 80% chance');
    // Frost is a word before it is a colour, and it carries its plain meaning.
    expect(read).toMatch(/killing frost/i);
    expect(read).toMatch(/at or below freezing/i);
  });

  it('server-renders a chart as its text half, with no canvas at all', () => {
    const markup = html(Chart, {
      plain: 'Daily high and low',
      themed: 'Warmth ahead',
      unit: '°C',
      summary: 'Highs 26 °C at most.',
      data: [
        [1, 2],
        [10, 11],
      ],
      series: [{ plain: 'Daily high', colorToken: '--moh-parched' }],
    });
    expect(markup).not.toContain('<canvas');
    expect(text(markup)).toContain('Highs 26 °C at most.');
    expect(text(markup)).toContain('Daily high');
  });

  it('says where it cannot look rather than showing a plausible sky', () => {
    const read = text(html(SiteMissing, {}));
    expect(read).toMatch(/does not know where to look/i);
  });
});

// ----------------------------------------------------------------- the theme

describe('the tokens', () => {
  const here = fileURLToPath(new URL('.', import.meta.url));
  const files = readdirSync(here, { recursive: true, encoding: 'utf8' }).filter(
    (name) => name.endsWith('.svelte') || (name.endsWith('.ts') && !name.endsWith('.test.ts')),
  );

  it('finds the whole screen, so this guard cannot quietly cover nothing', () => {
    expect(files.length).toBeGreaterThan(8);
  });

  it.each([
    ['a literal colour', /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/],
    ['a literal duration', /:\s*\d+m?s\b/],
  ])('never writes %s — the design re-pigments every token ', (_what, pattern) => {
    const offenders = files.filter((name) => pattern.test(readFileSync(here + name, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
