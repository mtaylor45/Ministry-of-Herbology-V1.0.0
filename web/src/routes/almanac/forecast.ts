/** Turning `ForecastPoint` rows into the two things the Almanac shows.
 *
 * Pure functions, no Svelte: the ten-day strip and the hourly trace are mostly
 * arithmetic and wording, and both are easier to be sure of when they can be
 * tested without a browser.
 *
 * Units are SI, as everything in this app is until the Ministry Office grows a
 * display-unit preference (the project conventions, Conventions).
 */

import type { ForecastPoint } from './api';

/** Water freezes here, whatever a plant's own tolerance is. */
export const FREEZING_C = 0;

/**
 * The headroom the frost guard works with: 3 °F, from the plan, kept identical
 * to `FROST_MARGIN_C` in `workers/weather/tasks.py`.
 */
export const FROST_MARGIN_C = (3 * 5) / 9;

/**
 * **The seam.** This strip reads frost off the forecast's own daily lows.
 *
 * It is a property of the *night*, not of a plant: a night at or below freezing
 * is a frost night, and one within the guard's 3 °F margin of freezing is worth
 * looking at. Which plants are actually at risk is a different question — it
 * needs each species' minimum temperature and whether the plant is in a pot or
 * in the ground — and it is answered by `GET /almanac/frost`, which this screen
 * deliberately does not call.
 *
 * the design turns that response from a bare `FrostAlert[]` into a
 * `FrostReport` — `{alerts, unassessable}` — so a plant the guard *cannot* judge
 * stops being invisible, and says the change is made now "precisely because it
 * is still free: The app's screens has not built the Almanac screen yet". It is still free:
 * nothing here reads that endpoint. When the envelope lands, the per-plant
 * alerts belong on this card beside these nights, and `unassessable` belongs
 * beside them.
 */
export type FrostRisk = 'frost' | 'near' | null;

export function frostRisk(lowC: number | null | undefined): FrostRisk {
  if (lowC === null || lowC === undefined) return null;
  if (lowC <= FREEZING_C) return 'frost';
  if (lowC <= FREEZING_C + FROST_MARGIN_C) return 'near';
  return null;
}

export const FROST_NOTE: Record<'frost' | 'near', { themed: string; plain: string }> = {
  frost: {
    themed: 'A killing frost',
    plain: 'At or below freezing overnight',
  },
  near: {
    themed: 'A cold night',
    plain: 'Within a degree or two of freezing overnight',
  },
};

/** The seven conditions the sources are normalised to, in
 *  `workers/weather/sources/base.py`. Anything else is shown as it arrives
 *  rather than silently dropped. */
export interface ConditionLabel {
  themed: string;
  plain: string;
  /** Only where the design system's set has an honest match. An icon is never the
   *  only carrier of the condition — the plain word is always beside it. */
  icon: 'sun' | 'rain' | 'frost' | null;
}

const CONDITIONS: Record<string, ConditionLabel> = {
  clear: { themed: 'Clear skies', plain: 'Clear', icon: 'sun' },
  partly_cloudy: { themed: 'Broken cloud', plain: 'Partly cloudy', icon: null },
  cloudy: { themed: 'Overcast', plain: 'Cloudy', icon: null },
  rain: { themed: 'Rain', plain: 'Rain', icon: 'rain' },
  snow: { themed: 'Snow', plain: 'Snow', icon: 'frost' },
  storm: { themed: 'A storm', plain: 'Storm', icon: 'rain' },
  fog: { themed: 'Fog', plain: 'Fog', icon: null },
};

export function conditionLabel(condition: string | null | undefined): ConditionLabel | null {
  if (!condition) return null;
  return (
    CONDITIONS[condition] ?? {
      themed: humanise(condition),
      plain: humanise(condition),
      icon: null,
    }
  );
}

function humanise(value: string): string {
  const spaced = value.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// ------------------------------------------------------------------ the ten days

export interface DailyRow {
  /** `YYYY-MM-DD` in the site's own calendar. */
  day: string;
  /** "Today", "Tomorrow", or "Fri 8 May". */
  label: string;
  /** For `<time datetime>` and for the table the chart is paired with. */
  iso: string;
  high: number | null;
  low: number | null;
  precipMm: number | null;
  precipProbPct: number | null;
  et0Mm: number | null;
  condition: ConditionLabel | null;
  frost: FrostRisk;
  point: ForecastPoint;
}

export interface LabelOptions {
  /** Injected so the labels are testable without freezing the clock. */
  today?: string;
  locale?: string;
  /** The zone hourly stamps are read in. Defaults to the reader's own. */
  timeZone?: string;
}

/**
 * The calendar day a daily point is about.
 *
 * Daily rows arrive stamped midnight UTC of the site's own day, so converting
 * them to the reader's local zone would move half of them to the day before —
 * the ten-day strip would open on yesterday for anybody west of Greenwich. The
 * date is therefore read off the stamp rather than through a `Date`.
 */
export function dayOf(point: ForecastPoint): string {
  return point.time.slice(0, 10);
}

export function dayLabel(day: string, options: LabelOptions = {}): string {
  const today = options.today ?? new Date().toISOString().slice(0, 10);
  if (day === today) return 'Today';
  if (day === addDays(today, 1)) return 'Tomorrow';
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return day;
  return new Intl.DateTimeFormat(options.locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(date);
}

export function addDays(day: string, delta: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + delta);
  return date.toISOString().slice(0, 10);
}

export function dailyRows(points: ForecastPoint[], options: LabelOptions = {}): DailyRow[] {
  return points.map((point) => {
    const day = dayOf(point);
    return {
      day,
      label: dayLabel(day, options),
      iso: point.time,
      high: point.temp_max_c ?? null,
      low: point.temp_min_c ?? null,
      precipMm: point.precip_mm ?? null,
      precipProbPct: point.precip_prob_pct ?? null,
      et0Mm: point.et0_mm ?? null,
      condition: conditionLabel(point.condition),
      frost: frostRisk(point.temp_min_c),
      point,
    };
  });
}

export function frostNights(rows: DailyRow[]): DailyRow[] {
  return rows.filter((row) => row.frost !== null);
}

/** The span the range bars are drawn against, rounded outwards to whole
 *  degrees so the axis reads like a thermometer rather than like a float.
 *
 *  The span is the week's own. Stretching it to include freezing in a warm week
 *  would squeeze every bar into the top third of its track to make room for a
 *  temperature nothing is near. In a week that *does* approach freezing the
 *  lows bring it into range by themselves, and `freezingPct` marks it. */
export function temperatureDomain(rows: DailyRow[]): { min: number; max: number } {
  const values = rows.flatMap((row) => [row.low, row.high]).filter(isNumber);
  if (!values.length) return { min: 0, max: 1 };
  const min = Math.floor(Math.min(...values)) - 1;
  const max = Math.ceil(Math.max(...values)) + 1;
  return { min, max: max > min ? max : min + 1 };
}

/** Where one day's low-to-high bar sits in that span, as percentages.
 *  A day missing either end gets no bar at all rather than a bar drawn from a
 *  number nobody has. */
export function rangeBar(
  row: DailyRow,
  domain: { min: number; max: number },
): { startPct: number; lengthPct: number } | null {
  if (!isNumber(row.low) || !isNumber(row.high)) return null;
  const span = domain.max - domain.min;
  if (span <= 0) return null;
  const start = ((row.low - domain.min) / span) * 100;
  const length = ((row.high - row.low) / span) * 100;
  return {
    startPct: clamp(start, 0, 100),
    // Always wide enough to see, even when the high and low are the same.
    lengthPct: clamp(length, 2, 100 - clamp(start, 0, 98)),
  };
}

/** Where freezing sits on the same span, so the strip can rule a line at it —
 *  or null when the week never comes near it, because a marker pinned to the
 *  end of every row is a mark that means nothing. */
export function freezingPct(domain: { min: number; max: number }): number | null {
  const span = domain.max - domain.min;
  if (span <= 0) return null;
  const at = ((FREEZING_C - domain.min) / span) * 100;
  return at < 1 || at > 99 ? null : at;
}

// ----------------------------------------------------------------- the one day

export interface HourlyRow {
  iso: string;
  /** Unix seconds — what uPlot plots on x. */
  at: number;
  label: string;
  tempC: number | null;
  precipMm: number | null;
  precipProbPct: number | null;
  condition: ConditionLabel | null;
  point: ForecastPoint;
}

/**
 * The hourly trace, in the reader's own zone.
 *
 * Hourly stamps are instants, so this one *is* a conversion. The site's
 * timezone is not on any endpoint the client can read (`fixtures/site.json` has
 * it; the contract has no `GET /sites`), so the browser's zone stands in. For a
 * self-hosted household app that is the household's zone — but it is a
 * stand-in, and the earlier pull request asks A for the site.
 */
export function hourlyRows(points: ForecastPoint[], options: LabelOptions = {}): HourlyRow[] {
  const format = new Intl.DateTimeFormat(options.locale, {
    hour: 'numeric',
    timeZone: options.timeZone,
  });
  return points.map((point) => {
    const date = new Date(point.time);
    return {
      iso: point.time,
      at: Math.round(date.getTime() / 1000),
      label: Number.isNaN(date.getTime()) ? point.time : format.format(date),
      tempC: point.temperature_c ?? null,
      precipMm: point.precip_mm ?? null,
      precipProbPct: point.precip_prob_pct ?? null,
      condition: conditionLabel(point.condition),
      point,
    };
  });
}

/** The day's extremes, read off the hourly trace rather than asked for twice. */
export function hourlyExtremes(rows: HourlyRow[]): { low: number | null; high: number | null } {
  const values = rows.map((row) => row.tempC).filter(isNumber);
  if (!values.length) return { low: null, high: null };
  return { low: Math.min(...values), high: Math.max(...values) };
}

export function totalPrecip(rows: { precipMm: number | null }[]): number {
  return round1(rows.reduce((sum, row) => sum + (row.precipMm ?? 0), 0));
}

// --------------------------------------------------------------------- wording

/** A temperature, or the plain fact that there is not one. */
export function formatTemp(value: number | null | undefined): string {
  return isNumber(value) ? `${round1(value)} °C` : 'not forecast';
}

export function formatPrecip(value: number | null | undefined): string {
  if (!isNumber(value)) return 'not forecast';
  return value === 0 ? 'none' : `${round1(value)} mm`;
}

export function formatProbability(value: number | null | undefined): string | null {
  return isNumber(value) ? `${Math.round(value)}% chance` : null;
}

/** Rain, and how likely it is — phrased so that neither half contradicts the
 *  other. "Rain none, 10% chance" reads as a 10% chance of no rain, which is
 *  the opposite of what the forecast means. */
export function rainSentence(row: {
  precipMm: number | null;
  precipProbPct: number | null;
}): string {
  const chance = formatProbability(row.precipProbPct);
  if (!isNumber(row.precipMm)) return 'Rain not forecast';
  if (row.precipMm === 0) return chance ? `No rain, ${chance} of any` : 'No rain';
  return chance ? `Rain ${round1(row.precipMm)} mm, ${chance}` : `Rain ${round1(row.precipMm)} mm`;
}

/** The sentence read aloud for one day of the strip, so the row means the same
 *  thing to a screen reader as the bar does to an eye. */
export function daySentence(row: DailyRow): string {
  const parts = [
    `${row.label}: high ${formatTemp(row.high)}, low ${formatTemp(row.low)}`,
    row.condition ? row.condition.plain : null,
    rainSentence(row).toLowerCase(),
    row.frost ? FROST_NOTE[row.frost].plain : null,
  ];
  return `${parts.filter(Boolean).join('. ')}.`;
}

export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

function isNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
