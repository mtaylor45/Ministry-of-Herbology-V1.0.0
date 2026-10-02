/** Showing how much an engine's answer is worth, wherever one is shown.
 *
 * Under the design nothing in the house measures the soil, and the engines
 * behind the Almanac and the scheduler are the only authority on whether a
 * plant is dry or about to freeze. Their worst failure is not being wrong — it
 * is losing an input and going on answering in the same confident voice,
 * because an app that has gone quiet looks exactly like a garden that needs
 * nothing.
 *
 * The weather engine's half of that is `workers/weather/quality.py`: every answer
 * carries `confidence`, `degraded` and a list of `degradations`, each a named
 * reason with a finished sentence in it. The scheduler's scheduler carries the
 * same three onto every task it generates, for the same reason — a watering
 * worked out from a degraded water balance is the next link in that chain.
 *
 * This module is the app's screens' half — the caveat goes **next to the number or the
 * instruction**, in the sentence the engine wrote, not behind a tooltip and not
 * in a colour. It lives in `shared/` rather than beside one screen because the
 * Almanac and Morning Rounds must not grow two vocabularies for one idea.
 */

import type { Confidence } from '$api/client';

export type { Confidence };

/** One named reason an answer is worth less than a clean measurement.
 *
 *  `detail` is a finished sentence, written by the engine to be shown to a
 *  reader as it stands. It is never summarised, truncated or reworded here:
 *  the wording is the engine's half of the contract with whoever is holding
 *  the phone. */
export interface Degradation {
  code: string;
  detail: string;
  caps_at: Confidence;
}

/** How sure an engine is, and why it is not surer.
 *
 *  the design puts this block on `WaterBalance` and `FrostAlert` and makes it
 *  required there. It does **not** put it on `ForecastPoint`, on `Series` or on
 *  `Task`: the Almanac's two endpoints carry nothing of the sort, and the three
 *  fields the scheduler serves on a task are additive beyond contract 1.2.0 and
 *  still waiting on the maintainers. Every field is therefore optional here, so a screen works
 *  whether or not they arrive — and `reportsItsOwnConfidence` below is how a
 *  screen tells "clean" apart from "did not say". */
export interface Assessment {
  confidence?: Confidence | null;
  degraded?: boolean;
  degradations?: Degradation[];
}

import type { Status } from '$ui/status';

/** Best to worst — the design allows exactly these four. */
export const CONFIDENCE_ORDER: Confidence[] = ['high', 'medium', 'low', 'unknown'];

export function rank(confidence: Confidence | null | undefined): number {
  const at = CONFIDENCE_ORDER.indexOf(confidence as Confidence);
  return at === -1 ? CONFIDENCE_ORDER.length - 1 : at;
}

/**
 * How much a *measurement or model* is worth, as a pill.
 *
 * Deliberately not `confidenceStatus` from the Specimen page: that vocabulary
 * ("Unattested — no source for this") is about whether a plant fact was cited,
 * and a forecast whose ET₀ went missing is not an uncited claim, it is a
 * measured one with a hole in it. Same four levels, different sentence.
 */
export function measurementConfidence(confidence: Confidence | null | undefined): Status {
  switch (confidence) {
    case 'high':
      return { themed: 'Read clearly', plain: 'High confidence', tone: 'thriving' };
    case 'medium':
      return { themed: 'Read through cloud', plain: 'Medium confidence', tone: 'sated' };
    case 'low':
      return { themed: 'Read poorly', plain: 'Low confidence — check it', tone: 'parched' };
    case 'unknown':
      return { themed: 'Unreadable', plain: 'Confidence unknown', tone: 'ailing' };
    default:
      return {
        themed: 'Not stated',
        plain: 'This reading does not say how sure it is',
        tone: 'parched',
      };
  }
}

/** The ceiling one degradation puts on an answer, said plainly. */
export function capSentence(degradation: Degradation): string {
  const level = measurementConfidence(degradation.caps_at).plain.replace(/ —.*$/, '');
  return `Caps this answer at: ${level.toLowerCase()}.`;
}

/**
 * Does this payload report its own confidence at all?
 *
 * **The seam.** the design requires the assessment block on `WaterBalance` and
 * `FrostAlert`. `/almanac/forecast` and `/almanac/history` — the two endpoints
 * the Almanac reads — are not covered by it and carry nothing. A screen that
 * shows nothing in that case
 * is a screen claiming the forecast is clean, which is the exact failure the
 * engine's confidence arithmetic was built to prevent — so when the block is
 * absent the screen says so once, plainly, instead of showing a reassuring
 * blank. When the fields arrive, every caveat below appears with no change
 * here beyond deleting the notice.
 *
 * Morning Rounds is on the other side of the same seam: The scheduler's scheduler serves
 * the three fields on every task today, additively, and the contract does not
 * carry them yet. `null` is a real answer there and is not silence — a
 * completed task has no confidence to recover, because the frozen `task` table
 * has no column it could have been kept in — so a stated `null` still counts
 * as reporting, and reads as "not stated" rather than as "high".
 */
export function reportsItsOwnConfidence(payload: Assessment | null | undefined): boolean {
  if (!payload) return false;
  return payload.confidence !== undefined || payload.degraded !== undefined;
}

/** The caveats to show, worst ceiling first. Empty is empty: a clean answer
 *  gets no decoration, so a caveat line means something on the day it appears. */
export function caveats(payload: Assessment | null | undefined): Degradation[] {
  const found = payload?.degradations ?? [];
  return [...found].sort((a, b) => rank(b.caps_at) - rank(a.caps_at));
}

export function isDegraded(payload: Assessment | null | undefined): boolean {
  return Boolean(payload?.degraded) || caveats(payload).length > 0;
}

/** One line summarising a degraded panel, for the screen-reader summary and for
 *  the collapsed state. The detail sentences are never folded into it — they
 *  are the weather engine's wording and they are shown in full. */
export function caveatSummary(payload: Assessment | null | undefined): string {
  const found = caveats(payload);
  if (!found.length) return '';
  const count = `${found.length} reason${found.length === 1 ? '' : 's'}`;
  return `${count} this may be wrong`;
}

/** The weakest confidence of several panels — what a screen built of them is
 *  worth as a whole, since a chain is worth its weakest link. */
export function weakest(...payloads: (Assessment | null | undefined)[]): Confidence | undefined {
  const stated = payloads.filter(reportsItsOwnConfidence).map((p) => p?.confidence);
  if (!stated.length) return undefined;
  return CONFIDENCE_ORDER[Math.max(...stated.map((c) => rank(c)))];
}
