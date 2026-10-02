/** The four facets of a Specimen page, and the cross-links between them.
 *
 * "Every facet shows see-also links to the other three. Cross-linking is the
 * feature, not a nicety." — so the link set is data, computed in one place and
 * asserted in one test, rather than three hand-written lists that drift.
 */

import type { IconName } from '$ui';

export type FacetId = 'register' | 'tending' | 'compendium' | 'journal';

export interface Facet {
  id: FacetId;
  /** The wizarding-botany name. Never rendered without `plain`. */
  themed: string;
  /** What the facet actually is. */
  plain: string;
  /** One line of what is on it, for the see-also row's meta text. */
  blurb: string;
  icon: IconName;
  /** False while the facet does not exist. The link still goes there, and the
   *  see-also row says so. All four are built as of an earlier release; the flag stays
   *  because the honest row is the right behaviour if a fifth is ever listed
   *  before it is written. */
  built: boolean;
}

export const FACETS: readonly Facet[] = [
  {
    id: 'register',
    themed: 'Register Entry',
    plain: 'Inventory record',
    blurb: 'Where it stands, where it came from, its pot, its soil and its photographs',
    icon: 'quill',
    built: true,
  },
  {
    id: 'tending',
    themed: 'Tending',
    plain: 'Care and schedule',
    blurb: 'Care values with their sources, the watering schedule, water balance and frost',
    icon: 'water',
    built: true,
  },
  {
    id: 'compendium',
    themed: 'Compendium',
    plain: 'What is known about the species',
    blurb: 'Summary, taxonomy, native range and toxicity, each with its citation',
    icon: 'book',
    built: true,
  },
  {
    id: 'journal',
    themed: "Naturalist's Journal",
    plain: 'Illustrated plate, field notes and photographs',
    blurb:
      'Its plate with where the picture came from, the household’s field notes, and its photographs oldest first',
    icon: 'book',
    built: true,
  },
];

export function facetPath(specimenId: string, facet: FacetId): string {
  return `/specimen/${specimenId}/${facet}`;
}

export function facet(id: FacetId): Facet {
  const found = FACETS.find((f) => f.id === id);
  if (!found) throw new Error(`facets: no facet named "${id}".`);
  return found;
}

export interface FacetLink extends Facet {
  href: string;
}

/** The other three facets, in page order, with their links resolved. */
export function seeAlso(current: FacetId, specimenId: string): FacetLink[] {
  return FACETS.filter((f) => f.id !== current).map((f) => ({
    ...f,
    href: facetPath(specimenId, f.id),
  }));
}
