/** The conditions record: what it was, indoors against outdoors.
 *
 * The comparison is the point of this view — a study that sits ten degrees
 * warmer and far drier than the garden is why the same plant is watered on
 * different rounds in each. Which makes the honesty problem sharper than
 * usual: nothing in this house measures anything indoors yet,
 * and a screen that draws two lines when it has one set of numbers has lied
 * about the only thing the reader came here to compare.
 *
 * So the indoor series is checked before it is drawn, and when it is not really
 * indoor readings the screen says so in a sentence instead of plotting it.
 */

import type { ChartSeries } from './chart';
import { FREEZING_C } from './forecast';
import type { HistoryWindow, Metric, Series } from './api';

export const METRICS: Record<Metric, { themed: string; plain: string; unit: string }> = {
  temperature_c: { themed: 'Warmth', plain: 'Temperature', unit: '°C' },
  humidity_pct: { themed: 'Humours of the air', plain: 'Humidity', unit: '%' },
  soil_moisture_pct: { themed: 'Damp in the soil', plain: 'Soil moisture', unit: '%' },
  precip_mm: { themed: 'Rainfall', plain: 'Rain', unit: 'mm' },
  et0_mm: { themed: 'Thirst of the air', plain: 'Evaporation (ET₀)', unit: 'mm' },
};

export const WINDOWS: Record<string, { themed: string; plain: string }> = {
  '1d': { themed: 'A day', plain: 'Last 24 hours' },
  '7d': { themed: 'A week', plain: 'Last 7 days' },
  '30d': { themed: 'A month', plain: 'Last 30 days' },
};

/** Metrics that only ever describe the site's weather. Asking for one of these
 *  by location is asking a question the rollups cannot answer — the indoor
 *  column comes from `reading_daily`, which the hub fills. */
export const OUTDOOR_ONLY: Metric[] = ['precip_mm', 'et0_mm'];

/** Metrics that only ever come from a sensor indoors. */
export const SENSOR_ONLY: Metric[] = ['soil_moisture_pct'];

export function hasAnyValue(series: Series | null | undefined): boolean {
  return Boolean(series?.values?.some((value) => value !== null && value !== undefined));
}

/**
 * Is this response actually the indoor record it was asked for?
 *
 * Two ways it is not, and both matter:
 *
 * - it came back empty, because no sensor has ever written a reading;
 * - it came back from `weather_daily`, which is the *site's outdoor weather*.
 *   The mock answers a location query with site weather today, and a line
 *   labelled "the Study" that is really the garden is the worst outcome this
 *   screen has: it invents an indoor climate and invites somebody to water on
 *   it.
 *
 * `source` is served by the weather engine and is not in the contract, so
 * the empty check stands on its own if the field ever goes away.
 */
export function indoorIsReal(series: Series | null | undefined): boolean {
  if (!hasAnyValue(series)) return false;
  return series?.source !== 'weather_daily';
}

/** Why the indoor line is missing, in a sentence that names the reason rather
 *  than shrugging. Returns null when there is nothing to explain. */
export function indoorGap(series: Series | null | undefined, metric: Metric): string | null {
  if (indoorIsReal(series)) return null;
  if (SENSOR_ONLY.includes(metric)) {
    return (
      'Nothing measures soil moisture in this house. the design makes the modelled ' +
      'water balance the shipping path, so there is no sensor record to compare ' +
      'against — and no figure has been estimated to fill the gap.'
    );
  }
  if (series?.source === 'weather_daily') {
    return (
      'The API answered this indoor question with the site’s outdoor weather, so ' +
      'there is nothing here that describes indoors. It is shown as one line, not ' +
      'two, rather than drawing the garden twice and calling half of it a room.'
    );
  }
  return (
    'No indoor readings have been stored yet. The sensor adapter has nothing ' +
    'connected to it in this house, so the record indoors is genuinely empty ' +
    'rather than hidden.'
  );
}

/** Metrics worth offering for a given place. Offering soil moisture for the
 *  site, or rainfall for a bedroom, is offering a question with no answer. */
export function metricsFor(place: 'site' | 'indoor'): Metric[] {
  const all = Object.keys(METRICS) as Metric[];
  return all.filter((metric) =>
    place === 'site' ? !SENSOR_ONLY.includes(metric) : !OUTDOOR_ONLY.includes(metric),
  );
}

export interface AlignedRow {
  at: number;
  outdoor: number | null;
  indoor: number | null;
  low: number | null;
  high: number | null;
}

/**
 * The two series on one timeline.
 *
 * Buckets are daily on both sides, but the two need not cover the same days —
 * a sensor fitted last Tuesday has nothing to say about last Monday. The union
 * of the timestamps keeps both honest: a gap stays a gap instead of sliding a
 * value onto the wrong day.
 */
export function align(outdoor: Series | null, indoor: Series | null): AlignedRow[] {
  const times = new Set<number>();
  for (const series of [outdoor, indoor]) for (const at of series?.times ?? []) times.add(at);

  const at = (series: Series | null, moment: number, column: 'values' | 'min' | 'max') => {
    if (!series) return null;
    const index = series.times.indexOf(moment);
    if (index === -1) return null;
    return series[column]?.[index] ?? null;
  };

  return [...times]
    .sort((a, b) => a - b)
    .map((moment) => ({
      at: moment,
      outdoor: at(outdoor, moment, 'values'),
      indoor: at(indoor, moment, 'values'),
      low: at(outdoor, moment, 'min'),
      high: at(outdoor, moment, 'max'),
    }));
}

/**
 * Does this record carry each day's extremes as well as its average?
 *
 * **The defect this exists to fix.** `Series` has carried `min` and `max` since
 * 1.0 and the daily rollup fills them, but the chart plotted `values` alone —
 * the daily *mean*. Over a week of frost the mean stays several degrees above
 * freezing while the nights go below it, so on the screen built to show a month
 * of weather the one thing an earlier release is about was invisible: a night at −2 °C read as
 * a day at 3.5 °C. The forecast strip on the sibling screen has drawn highs and
 * lows. The record now draws them too, from columns the API was
 * already serving.
 */
export function hasRange(rows: AlignedRow[]): boolean {
  return rows.some((row) => isNumber(row.low) || isNumber(row.high));
}

export interface ChartShape {
  /** Draw the daily low and high rather than the daily mean. */
  range: boolean;
  /** Draw the indoor series beside it. */
  indoor: boolean;
}

/** uPlot wants columns: `[xs, ...ys]`, x in unix seconds. The y columns are in
 *  the order `seriesFor` names them, and the two must not drift apart — a
 *  legend that labels the wrong line is worse than no legend. */
export function columns(rows: AlignedRow[], shape: ChartShape): (number | null)[][] {
  const xs = rows.map((row) => row.at);
  const data: (number | null)[][] = [xs];
  if (shape.range) {
    data.push(rows.map((row) => row.high));
    data.push(rows.map((row) => row.low));
  } else {
    data.push(rows.map((row) => row.outdoor));
  }
  if (shape.indoor) data.push(rows.map((row) => row.indoor));
  return data;
}

/** The lines, named before they are coloured, in the same order as `columns`.
 *
 *  Every one is told apart by shape as well as by hue — the guide's own
 *  accessibility rule (§25) and WCAG 1.4.1 — because this screen is read on a
 *  phone in daylight where two hues are one hue. The tokens are read off the
 *  theme at draw time (`chart.ts`); nothing here names a colour. */
export function seriesFor(shape: ChartShape, roomName: string | null): ChartSeries[] {
  const out: ChartSeries[] = shape.range
    ? [
        { plain: 'Daily high, outdoors', colorToken: '--moh-parched' },
        { plain: 'Daily low, outdoors', colorToken: '--moh-frost', dash: true },
      ]
    : [{ plain: 'Outdoors', colorToken: '--moh-accent' }];
  if (shape.indoor) {
    out.push({
      plain: `Indoors — ${roomName ?? 'inside'}`,
      colorToken: '--moh-sage',
      dash: true,
    });
  }
  return out;
}

/** The plain summary a reader gets without reading the chart: the range, the
 *  coldest night where the record gives one, and the difference between inside
 *  and out where there is one. */
export function summary(rows: AlignedRow[], metric: Metric, shape: ChartShape): string {
  const unit = METRICS[metric].unit;
  const means = rows.map((row) => row.outdoor).filter(isNumber);
  const lows = rows.map((row) => row.low).filter(isNumber);
  const highs = rows.map((row) => row.high).filter(isNumber);
  const outdoor = shape.range && (lows.length || highs.length) ? [...lows, ...highs] : means;
  if (!outdoor.length) return 'Nothing has been recorded for this period.';

  const low = round(Math.min(...outdoor));
  const high = round(Math.max(...outdoor));
  const parts = [`Outdoors ranged from ${low} ${unit} to ${high} ${unit}`];

  if (shape.indoor) {
    const indoor = rows.map((row) => row.indoor).filter(isNumber);
    if (indoor.length) {
      parts.push(
        `indoors from ${round(Math.min(...indoor))} ${unit} to ${round(Math.max(...indoor))} ${unit}`,
      );
    }
  }
  return `${parts.join(', ')}.`;
}

/**
 * The nights this record says fell to freezing or below.
 *
 * A property of the *night*, and of water — not of a plant. Which plants were
 * at risk on any of them needs each one's own threshold and whether it stands
 * in a pot or in the ground, and that is the frost guard's answer with its own
 * source behind it. This sentence claims nothing about a plant, and it
 * is drawn from `min`, never from the mean.
 */
export function freezingNights(rows: AlignedRow[], metric: Metric): AlignedRow[] {
  if (metric !== 'temperature_c') return [];
  return rows.filter((row) => isNumber(row.low) && row.low <= FREEZING_C);
}

export function freezingSentence(
  rows: AlignedRow[],
  metric: Metric,
  locale?: string,
): string | null {
  const cold = freezingNights(rows, metric);
  if (!cold.length) return null;
  const days = cold.map((row) => bucketLabel(row.at, locale)).join(', ');
  const coldest = round(Math.min(...cold.map((row) => row.low as number)));
  return (
    `${cold.length === 1 ? 'One night' : `${cold.length} nights`} in this record fell to freezing ` +
    `or below — ${days}. The coldest reached ${coldest} °C. That is the night’s temperature and ` +
    'not a judgement about any plant: what each one can take is its own threshold, with its own ' +
    'source, and the frost guard is where that is answered.'
  );
}

/**
 * Which rollup answered, in the API's own word and then in plain English.
 *
 * The weather engine names the table on `source`. It is worth printing because the
 * two are not interchangeable: `weather_daily` is the site's outdoor weather
 * and `reading_daily` is a sensor indoors, and a line labelled "the Study" that
 * is really the garden is the worst outcome this screen has. Absent when E
 * says nothing, rather than guessed at.
 */
export function rollupSentence(series: Series | null | undefined): string | null {
  if (!series?.source) return null;
  const known: Record<string, string> = {
    weather_daily: 'the site’s own daily weather record',
    reading_daily: 'daily sensor readings stored for a location',
  };
  const plain = known[series.source];
  return plain
    ? `Read from ${plain} (${series.source}).`
    : `Read from the rollup the API calls ${series.source}, which this screen has no plainer name for.`;
}

/**
 * The record is shorter than the window asked for.
 *
 * "Last 30 days" over nine days of record is a chart that looks like three
 * quiet weeks. The number of days is read off the response, never assumed —
 * `fixtures/` belongs to the test suite and L re-cuts it, so a figure
 * this screen wrote down would be a figure that goes stale without failing.
 */
export const WINDOW_DAYS: Record<HistoryWindow, number> = { '1d': 1, '7d': 7, '30d': 30 };

export function coverageSentence(rows: AlignedRow[], window: HistoryWindow): string | null {
  const asked = WINDOW_DAYS[window];
  const got = rows.length;
  if (!got || got >= asked) return null;
  return (
    `The record holds ${got} ${got === 1 ? 'day' : 'days'}, not ${asked}. What is drawn is the ` +
    'whole of it — the weather ingest has not stored any further back for this site — rather ' +
    `than ${asked} days with most of them left blank.`
  );
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

/** The date a bucket is about, for the table beside the chart. */
export function bucketLabel(at: number, locale?: string): string {
  const date = new Date(at * 1000);
  if (Number.isNaN(date.getTime())) return String(at);
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(date);
}

function isNumber(value: number | null): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** A window or metric asked for in the URL, or the sensible default. The three
 *  views are linkable, so the query string is input from outside and is treated
 *  as such: anything unrecognised falls back rather than reaching the API. */
export function parseWindow(value: string | null): HistoryWindow {
  return value === '1d' || value === '7d' || value === '30d' ? value : '7d';
}

export function parseMetric(value: string | null): Metric {
  return value !== null && value in METRICS ? (value as Metric) : 'temperature_c';
}
