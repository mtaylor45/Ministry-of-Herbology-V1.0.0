/** Saying what is stale, rather than lying.
 *
 * Offline scope is decided: care pages and the current Morning Rounds are
 * cached, maps and charts are not. Anything served from cache says so and says
 * how old it is — an app that silently shows yesterday's frost warning is worse
 * than one that shows nothing.
 */

export type Timestamp = Date | string | number | null | undefined;

function toDate(value: Timestamp): Date | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "4 minutes ago", "2 days ago", "never fetched" — plain language, always. */
export function formatAsOf(asOf: Timestamp, now: Date = new Date()): string {
  const date = toDate(asOf);
  if (!date) return 'never fetched';

  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (seconds < 0) return 'just now';
  if (seconds < 60) return 'moments ago';

  const units: [number, string][] = [
    [60, 'minute'],
    [60, 'hour'],
    [24, 'day'],
  ];
  let value = seconds;
  let unit = 'second';
  for (const [size, name] of units) {
    if (value < size) break;
    value = Math.floor(value / size);
    unit = name;
  }
  return `${value} ${unit}${value === 1 ? '' : 's'} ago`;
}

/**
 * The sentence a stale panel shows. `what` is the plain name of the data, so
 * the reader learns which part of the screen they cannot trust.
 */
export function staleSentence(what: string, asOf: Timestamp, now: Date = new Date()): string {
  const date = toDate(asOf);
  if (!date) return `${what} has never been fetched on this device.`;
  return `${what} is the stored copy, last updated ${formatAsOf(date, now)}.`;
}
