/** The fourth facet's own logic: which leaf is this plant's, and how the
 *  photo growth log is ordered and described.
 *
 *  The plate half is the journal's. `leafFor()` hands the Specimen page's own
 *  record to the journal's `buildPages()` rather than restating the matching rule, so a
 *  plate can never belong to a plant on this facet and to a different one in
 *  the book — the two screens cannot disagree because they share the function.
 *
 *  The growth log half is this parts of the project's. The contract serves photographs
 *  *newest first* (`listPhotos`), which is the right order for a Register
 *  entry and the wrong one for a growth log: a log is read forward, from the
 *  cutting to the plant it became. So the order is turned here, once, and a
 *  test pins it.
 */

import { buildPages, type JournalPage, type Plate } from '../../../journal/plates';
import type { Photo, SpecimenDetail } from '../api';

export type { JournalPage, Photo, Plate };

/** This plant's leaf, by the same rule the book uses. A `SpecimenDetail` is a
 *  superset of the `JournalSpecimen` the journal reads, so nothing is reshaped. */
export function leafFor(specimen: SpecimenDetail, plates: Plate[]): JournalPage {
  return buildPages([specimen], plates)[0];
}

/** When a photograph was taken, as a number for sorting. `NaN` for a value
 *  that will not parse, which the sort below sends to the end rather than
 *  letting it land somewhere arbitrary in the middle of the record. */
function takenAt(photo: Photo): number {
  return new Date(photo.taken_at).getTime();
}

/** The growth log's order: oldest first, newest last, so the log reads the way
 *  the plant grew. Stable, so two photographs from the same moment keep the
 *  order the API served them in. Does not mutate its input. */
export function oldestFirst(photos: readonly Photo[]): Photo[] {
  return [...photos].sort((a, b) => {
    const ta = takenAt(a);
    const tb = takenAt(b);
    if (Number.isNaN(ta) && Number.isNaN(tb)) return 0;
    if (Number.isNaN(ta)) return 1;
    if (Number.isNaN(tb)) return -1;
    return ta - tb;
  });
}

/** Real alt text for a growth-log photograph: the caption where the household
 *  wrote one, otherwise what and when, never an empty string on a picture
 *  that carries meaning. */
export function photoAlt(photo: Photo, specimenName: string, when: string): string {
  const caption = photo.caption?.trim();
  if (caption) return caption;
  return `Photograph of ${specimenName}, taken ${when}`;
}

/** One sentence above the log saying how much of the plant's life it covers. */
export function growthLogSentence(count: number, first: string, last: string): string {
  if (count === 0) return 'No photographs have been recorded for this plant.';
  if (count === 1) return `One photograph, taken ${first}.`;
  return `${count} photographs, oldest first, from ${first} to ${last}.`;
}

/** What an empty growth log says. Since the inventory API's change a photograph can be added
 *  from this facet, so the empty state points at the control below it. */
export const FIRST_PHOTO =
  'Nothing has been photographed yet. Add the first photograph below — a growth log is ' +
  'most useful started early.';
