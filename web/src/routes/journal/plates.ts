/** What the book view shows on each page, including the pages with no plate.
 *
 * Pure functions over what the API returned, so the two things most likely to
 * be got wrong here are testable without a browser: **which plant a plate
 * belongs to**, and **what a reader is told about where the picture came
 * from.**
 *
 * ## The book pages through every plant, not every plate
 *
 * the earlier exit criterion is *"each specimen has an approved plate; the book view
 * pages through all"*, and the trap in it is the coverage target. A book built
 * from the plates it happens to have would page through nine pages and look
 * complete. This one has a page per **specimen**, and a plant with no plate
 * gets a page that says so in words.
 *
 * That is the same decision the design made for `MorningRounds.unscheduled[]`:
 * *a plant with no task is indistinguishable from a plant that needs nothing*,
 * so the list has to name the ones it could not judge. A plant missing from a
 * book of plates is indistinguishable from a plant nobody owns.
 *
 * ## Three states, and the middle one is the interesting one
 *
 * - `plate` — an approved plate. Somebody vouched for this likeness.
 * - `waiting` — a plate exists and nobody has accepted it yet. It is **shown**,
 *   marked, with the approval still outstanding. Hiding it would make the book
 *   look thinner than the work actually is, and auto-approving it to fill the
 *   page is the thing this release is not allowed to do.
 * - `absent` — no plate. Named, with the plant's name, on its own page.
 */

import type { JournalSpecimen, Plate, PlateCoverage, PlateCoverageEntry } from './api';

export type { JournalSpecimen, Plate, PlateCoverage, PlateCoverageEntry };

export type PageState = 'plate' | 'waiting' | 'absent';

export interface JournalPage {
  specimen: JournalSpecimen;
  plate: Plate | null;
  state: PageState;
  /** The plant's botanical name where one is known, for alt text and captions. */
  botanicalName: string | null;
}

/** Pair each specimen with its plate, in register order.
 *
 * A plate may name a specimen (somebody's own photograph of *this* plant) or a
 * species (one plate serving every *Monstera deliciosa* in the house). A
 * specimen-level plate wins, because it is a picture of this actual plant.
 *
 * **Nothing here falls back to another species' plate.** A congener's picture
 * is a wrong answer that looks like a right one, and the match below is by id
 * only — no genus matching, no nearest-relative, no "close enough".
 */
export function buildPages(specimens: JournalSpecimen[], plates: Plate[]): JournalPage[] {
  const bySpecimen = new Map<string, Plate>();
  const bySpecies = new Map<string, Plate>();
  for (const plate of plates) {
    if (plate.specimen_id && !bySpecimen.has(plate.specimen_id)) {
      bySpecimen.set(plate.specimen_id, plate);
    } else if (plate.species_id && !bySpecies.has(plate.species_id)) {
      bySpecies.set(plate.species_id, plate);
    }
  }

  return specimens.map((specimen) => {
    const speciesId = specimen.species?.id ?? null;
    const plate =
      bySpecimen.get(specimen.id) ?? (speciesId ? bySpecies.get(speciesId) : undefined) ?? null;
    return {
      specimen,
      plate,
      state: plate ? (plate.approved ? 'plate' : 'waiting') : 'absent',
      botanicalName: specimen.species?.accepted_name ?? null,
    };
  });
}

export interface Coverage {
  total: number;
  approved: number;
  waiting: number;
  absent: number;
  generated: number;
  sourced: number;
}

/** The real numbers, for the line the book prints above itself.
 *
 * Reported rather than rounded: "9 of 12 have a plate" is a fact a reader can
 * act on, and "complete" would be a claim nobody checked.
 */
export function coverage(pages: JournalPage[]): Coverage {
  const withPlate = pages.filter((page) => page.plate);
  return {
    total: pages.length,
    approved: pages.filter((page) => page.state === 'plate').length,
    waiting: pages.filter((page) => page.state === 'waiting').length,
    absent: pages.filter((page) => page.state === 'absent').length,
    generated: withPlate.filter((page) => page.plate?.origin === 'generated').length,
    sourced: withPlate.filter((page) => page.plate?.origin === 'public_domain').length,
  };
}

/** One sentence of coverage, in plain words. */
export function coverageSentence(count: Coverage): string {
  if (count.total === 0) return 'There are no plants in the register yet, so the book is empty.';
  const parts = [`${count.approved} of ${count.total} plants have an approved plate`];
  if (count.waiting) parts.push(`${count.waiting} waiting to be accepted`);
  if (count.absent) parts.push(`${count.absent} with no plate at all`);
  if (count.generated) {
    parts.push(
      `${count.generated} ${count.generated === 1 ? 'is' : 'are'} drawn by software rather than collected`,
    );
  }
  return `${parts.join(', ')}.`;
}

/** The visible provenance line, which is the point of the whole releases.
 *
 * Returned as data rather than rendered here so one test can assert what a
 * reader is told, and so the plate component cannot grow a second version of
 * these sentences.
 *
 * A generated plate's line is **not** a caveat appended to a credit. It is the
 * credit's replacement: `license` and `attribution` are null on a generated
 * plate by construction (`workers/plates/domain.py`), so there is nothing to
 * append it to.
 */
export interface Provenance {
  /** 'drawn' is the one that must never be missable. */
  kind: 'collected' | 'drawn' | 'own';
  themed: string;
  plain: string;
  /** The licence and credit, when the plate earned one. */
  credit: string | null;
}

export function provenanceOf(plate: Plate): Provenance {
  if (plate.origin === 'generated') {
    return {
      kind: 'drawn',
      themed: 'Drawn to order',
      plain: 'Illustration generated by software — not a historical plate',
      credit: null,
    };
  }
  if (plate.origin === 'user_upload') {
    return {
      kind: 'own',
      themed: 'From the household',
      plain: 'Your own photograph',
      credit: plate.attribution,
    };
  }
  return {
    kind: 'collected',
    themed: 'Collected',
    plain: 'A plate from a public collection',
    credit: creditLine(plate),
  };
}

/** `attribution — licence`, with whichever halves exist. */
export function creditLine(plate: Plate): string | null {
  const parts = [plate.attribution, plate.license ? formatLicence(plate.license) : null].filter(
    (part): part is string => Boolean(part && part.trim()),
  );
  return parts.length ? parts.join(' — ') : null;
}

/** `cc by-sa 4.0` reads badly in a caption; `CC BY-SA 4.0` reads correctly.
 *
 * Presentation only. The stored value keeps the canonical lower-case spelling
 * the API serves, so nothing downstream has to guess which form it has.
 */
export function formatLicence(licence: string): string {
  const trimmed = licence.trim();
  if (/^public domain$/i.test(trimmed)) return 'Public domain';
  // `cc by-sa 4.0` -> `CC BY-SA 4.0`; the version is left alone.
  return trimmed
    .split(' ')
    .map((word) => (/^(cc0?|by|sa|by-sa|by-nc)$/i.test(word) ? word.toUpperCase() : word))
    .join(' ');
}

/** Real alt text: what it is, and whether anybody drew it.
 *
 * The definition of done asks for alt text that says what the picture is *and* whether it was
 * generated. A screen-reader user who is told only "plate of Monstera
 * deliciosa" has been told the same thing a sighted reader is told by the
 * picture — and strictly less than the one who can also see the label beside
 * it. So the generated case says so inside the alt text as well, because an
 * `aria-hidden` caption next to an honest-looking image is exactly the gap
 * the design refused to leave behind a tooltip.
 */
export function altTextFor(page: JournalPage): string {
  const name = page.botanicalName ?? page.specimen.display_name;
  if (!page.plate) return '';
  if (page.plate.origin === 'generated') {
    return (
      `A botanical illustration of ${name} in a nineteenth-century style, ` +
      'generated by software. It is not a scan of a historical plate.'
    );
  }
  if (page.plate.origin === 'user_upload') {
    return `A photograph of ${page.specimen.display_name}, taken by the household.`;
  }
  const credit = creditLine(page.plate);
  return `A botanical plate of ${name} from a public collection` + (credit ? `. ${credit}.` : '.');
}

/** Why this page has no plate, in words, without inventing a cause.
 *
 * an earlier release shipped the generic half of this, because the contract had nowhere to
 * carry a reason and guessing "nothing was found" when the truth might be
 * "the volume is unmounted" would have been the invented answer. the design
 * gave the reason a home, so `entry` is now passed when `/journal/coverage`
 * answered and the sentence says which of the six cases this is.
 *
 * Without `entry` — coverage failed, or this client met a `reason_kind` it
 * does not know — it falls back to exactly the earlier sentence. A blank leaf with
 * no explanation is worse than one with it, and much better than no book.
 */
export function absenceSentence(page: JournalPage, entry?: PlateCoverageEntry): string {
  const name = page.botanicalName ?? page.specimen.display_name;
  const opening = `No plate has been recorded for ${name} yet.`;
  const closing =
    'The journal would rather leave the page blank than fill it with another ' + "plant's picture.";
  const because = entry ? absenceCause(entry) : null;
  if (!because) {
    return (
      `${opening} Public-domain sourcing found nothing this deployment could use, ` +
      `or has not run for this plant. ${closing}`
    );
  }
  return `${opening} ${because} ${closing}`;
}

/** The middle clause, chosen by `reason_kind`.
 *
 * Deliberately *not* `entry.reason` verbatim: that sentence is the pipeline's
 * own and is written for an operator reading a log. These are written for
 * somebody holding a watering can. `reason` is still shown, under the
 * sentence, by the component — the two say the same thing at different
 * altitudes, which is the pairing rule this app applies to everything else.
 *
 * Returns `null` for a kind this client does not recognise, so a seventh kind
 * added to the contract degrades to the generic sentence instead of a blank.
 */
export function absenceCause(entry: PlateCoverageEntry): string | null {
  switch (entry.reason_kind) {
    case 'no_candidate':
      return 'Every catalogue this deployment can ask was asked, and none of them had this species.';
    case 'unlicensed_candidate':
      return (
        'A catalogue offered one and stated no licence this deployment could record, ' +
        'so it was discarded rather than relabelled.'
      );
    case 'generation_unavailable':
      return (
        'Nothing was found, and no illustration generator is configured — so there is ' +
        'nothing to draw one with, and nothing was invented instead.'
      );
    case 'unusable_image':
      return 'An illustration was found but the file would not open, so it was not kept.';
    case 'store_unavailable':
      return 'This deployment has nowhere to keep plates yet, so none can be collected or drawn.';
    case 'not_run':
      return 'Nothing has looked for one yet.';
    default:
      return null;
  }
}

/** Pair each leaf with its coverage entry, by specimen id. */
export function coverageBySpecimen(
  coverage: PlateCoverage | null,
): Map<string, PlateCoverageEntry> {
  const out = new Map<string, PlateCoverageEntry>();
  for (const entry of coverage?.specimens ?? []) out.set(entry.specimen.id, entry);
  return out;
}

/** Clamp a page index into the book, so a bad URL lands on page one. */
export function clampIndex(index: number, pages: unknown[]): number {
  if (!pages.length) return 0;
  if (!Number.isFinite(index) || index < 0) return 0;
  return Math.min(Math.floor(index), pages.length - 1);
}

/** Where a given plant sits in the book, or `null` if it is not in it. */
export function indexOfSpecimen(pages: JournalPage[], specimenId: string): number | null {
  const at = pages.findIndex((page) => page.specimen.id === specimenId);
  return at === -1 ? null : at;
}
