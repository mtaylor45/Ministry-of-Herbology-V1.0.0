/** The conditions record's 7-day and 30-day charts.
 *
 * The defect this suite exists to hold shut: `Series` has carried `min` and
 * `max` since contract 1.0 and the daily rollup fills them, but the chart drew
 * `values` alone — the daily mean. Over a week of frost the mean stays several
 * degrees above freezing while the nights go under it, so on the one screen
 * built to show a month of weather the thing an earlier release is about was invisible.
 *
 * Nothing here writes down a number read out of `fixtures/`: the
 * series are built in the test, and the assertions are about the property — a
 * low below the mean survives to the chart, a short record says it is short.
 */

import { describe, expect, it } from 'vitest';
import {
  WINDOW_DAYS,
  align,
  columns,
  coverageSentence,
  freezingNights,
  freezingSentence,
  hasRange,
  seriesFor,
  summary,
} from './history';
import type { Series } from './api';

function series(overrides: Partial<Series> = {}): Series {
  return {
    metric: 'temperature_c',
    unit: '°C',
    times: [1792627200, 1792713600, 1792800000],
    values: [8.5, 3.5, 4.5],
    min: [4, -2, -1],
    max: [13, 9, 10],
    source: 'weather_daily',
    ...overrides,
  };
}

const COLD = align(series(), null);

describe('the daily extremes reach the chart', () => {
  it('notices when the rollup carries them', () => {
    expect(hasRange(COLD)).toBe(true);
    expect(hasRange(align(series({ min: [], max: [] }), null))).toBe(false);
    expect(hasRange([])).toBe(false);
  });

  it('plots the low and the high, not the mean, when they are there', () => {
    const shape = { range: true, indoor: false };
    const data = columns(COLD, shape);
    expect(data).toHaveLength(3);
    const [, highs, lows] = data;
    expect(highs).toEqual(COLD.map((row) => row.high));
    expect(lows).toEqual(COLD.map((row) => row.low));
    // The point of the whole change: the coldest number on the chart is below
    // the coldest mean, so a freezing night is visible as one.
    expect(Math.min(...(lows as number[]))).toBeLessThan(
      Math.min(...COLD.map((row) => row.outdoor as number)),
    );
  });

  it('falls back to the mean where the rollup carries no extremes', () => {
    const flat = align(series({ min: [], max: [] }), null);
    const data = columns(flat, { range: false, indoor: false });
    expect(data).toHaveLength(2);
    expect(data[1]).toEqual(flat.map((row) => row.outdoor));
  });

  it('keeps the indoor column last, so the legend cannot label the wrong line', () => {
    const indoor = series({ source: 'reading_daily', values: [19, 19.5, 20], min: [], max: [] });
    const rows = align(series(), indoor);
    const shape = { range: true, indoor: true };
    expect(columns(rows, shape)).toHaveLength(4);
    const names = seriesFor(shape, 'the Study').map((line) => line.plain);
    expect(names).toEqual(['Daily high, outdoors', 'Daily low, outdoors', 'Indoors — the Study']);
  });

  it('tells every line apart by shape as well as by colour', () => {
    const lines = seriesFor({ range: true, indoor: true }, 'the Study');
    const tokens = new Set(lines.map((line) => line.colorToken));
    expect(tokens.size).toBe(lines.length);
    // WCAG 1.4.1, and a phone in daylight: at least one of any pair differs by
    // dash, not only by hue.
    expect(lines.filter((line) => line.dash).length).toBeGreaterThan(0);
    for (const line of lines) expect(line.colorToken).toMatch(/^--moh-/);
  });

  it('names the room on the indoor line, so it is never the house as a whole', () => {
    expect(seriesFor({ range: false, indoor: true }, 'Kitchen Sill')[1].plain).toBe(
      'Indoors — Kitchen Sill',
    );
    expect(seriesFor({ range: false, indoor: true }, null)[1].plain).toBe('Indoors — inside');
  });
});

describe('the summary, for anyone not reading the chart', () => {
  it('spans the extremes when the extremes are what is drawn', () => {
    const said = summary(COLD, 'temperature_c', { range: true, indoor: false });
    const lows = COLD.map((row) => row.low as number);
    const highs = COLD.map((row) => row.high as number);
    expect(said).toContain(`${Math.min(...lows)} °C`);
    expect(said).toContain(`${Math.max(...highs)} °C`);
  });

  it('spans the means when the means are what is drawn', () => {
    const flat = align(series({ min: [], max: [] }), null);
    const said = summary(flat, 'temperature_c', { range: false, indoor: false });
    const means = flat.map((row) => row.outdoor as number);
    expect(said).toContain(`${Math.min(...means)} °C`);
  });

  it('says nothing is recorded rather than showing an empty range', () => {
    expect(summary([], 'temperature_c', { range: true, indoor: false })).toMatch(
      /Nothing has been recorded/,
    );
  });
});

describe('a freezing night in the record', () => {
  it('is found in the daily low, never in the mean', () => {
    const cold = freezingNights(COLD, 'temperature_c');
    expect(cold.length).toBeGreaterThan(0);
    for (const row of cold) expect(row.low as number).toBeLessThanOrEqual(0);
    // Every mean in this record is above freezing, which is exactly why the
    // mean could not have found them.
    for (const row of COLD) expect(row.outdoor as number).toBeGreaterThan(0);
  });

  it('is a fact about the night and says so — never about a plant', () => {
    const said = freezingSentence(COLD, 'temperature_c', 'en-GB') ?? '';
    expect(said).toMatch(/not a judgement about any plant/);
    expect(said).toMatch(/its own threshold/);
    expect(said).toMatch(/frost guard/);
  });

  it('counts one night as one', () => {
    const one = align(series({ times: [1], values: [3], min: [-1], max: [8] }), null);
    expect(freezingSentence(one, 'temperature_c')).toMatch(/^One night/);
  });

  it('is silent about a metric that is not a temperature', () => {
    expect(freezingNights(COLD, 'humidity_pct')).toEqual([]);
    expect(freezingSentence(COLD, 'humidity_pct')).toBeNull();
  });

  it('is silent about a warm record, so the notice means something when it appears', () => {
    const warm = align(series({ min: [4, 5, 6], max: [13, 14, 15] }), null);
    expect(freezingSentence(warm, 'temperature_c')).toBeNull();
  });
});

describe('a record shorter than the window asked for', () => {
  it('says how short, rather than drawing three quiet weeks', () => {
    const said = coverageSentence(COLD, '30d') ?? '';
    expect(said).toContain(`${COLD.length} days`);
    expect(said).toContain('not 30');
    expect(said).toMatch(/whole of it/);
  });

  it('says nothing when the record covers what was asked', () => {
    const week = align(
      series({
        times: Array.from({ length: 7 }, (_, i) => i + 1),
        values: Array.from({ length: 7 }, () => 10),
        min: [],
        max: [],
      }),
      null,
    );
    expect(coverageSentence(week, '7d')).toBeNull();
    expect(coverageSentence([], '30d')).toBeNull();
  });

  it('counts a day as a day for every window it offers', () => {
    expect(Object.keys(WINDOW_DAYS).sort()).toEqual(['1d', '30d', '7d']);
    expect(WINDOW_DAYS['7d']).toBe(7);
    expect(WINDOW_DAYS['30d']).toBe(30);
  });
});
