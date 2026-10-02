/** The book: every plant in the register, with its plate or the fact it has none.
 *
 * Two reads, settled separately (`settle()` in `../shared/http.ts`): the
 * plates, and the register. Both are needed, and for different reasons —
 * without the register the book could only page through the plates it has,
 * which is the version that looks complete at nine pages out of twelve.
 *
 * If the register fails and the plates arrive, the page says so rather than
 * silently showing a shorter book. That is the whole point of the screen.
 */

import {
  reads,
  settle,
  type Fetched,
  type JournalSpecimen,
  type Member,
  type Plate,
  type PlateCoverage,
} from './api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const [plates, specimens, members, coverage] = await Promise.all([
    settle(reads.plates(fetch)),
    settle(reads.specimens(fetch)),
    // The member picker for approvals. A failure here costs the
    // approve button and nothing else, so the book still reads.
    settle(reads.members(fetch)),
    // Why each blank leaf is blank. An *extra* read: if it
    // fails the book still pages through every plant and still says which
    // have no plate, it just cannot say why.
    settle(reads.coverage(fetch)),
  ]);

  return {
    plates: plates as Fetched<Plate[]>,
    specimens: (specimens.value
      ? { value: specimens.value.items, error: null }
      : { value: null, error: specimens.error }) as Fetched<JournalSpecimen[]>,
    members: members as Fetched<Member[]>,
    coverage: coverage as Fetched<PlateCoverage>,
    /** `?plant=<id>` opens the book at one plant, so the Specimen page can link
     *  straight to its leaf rather than to page one. */
    openAt: url.searchParams.get('plant'),
  };
};
