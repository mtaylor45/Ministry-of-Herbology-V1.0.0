/** One plant's journal: its plate, and its field notes.
 *
 * This is the content of the Specimen page's fourth facet. The facet route
 * itself — `/specimen/:id/journal` — lives under `web/src/routes/specimen/`,
 * which belongs to the app's screens, so K ships the page here and the app's screens'
 * remaining job is one route file that renders this and a `built: true` in
 * `facets.ts`. Until then this page is reachable on its own and the book view
 * links to it, so nothing about the feature waits on the app's screens.
 *
 * Each read settles separately: a plant whose notes fail to load should still
 * show its plate, and the other way round.
 */

import {
  reads,
  settle,
  type Fetched,
  type FieldNote,
  type JournalSpecimen,
  type Member,
  type Plate,
  type PlateCoverage,
} from '../api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const specimenId = params.specimen_id;
  const [specimen, plates, notes, members, coverage] = await Promise.all([
    settle(reads.specimen(specimenId, fetch)),
    settle(reads.plates(fetch)),
    settle(reads.notes(specimenId, fetch)),
    settle(reads.members(fetch)),
    settle(reads.coverage(fetch)),
  ]);

  return {
    specimenId,
    specimen: specimen as Fetched<JournalSpecimen>,
    plates: plates as Fetched<Plate[]>,
    notes: notes as Fetched<FieldNote[]>,
    members: members as Fetched<Member[]>,
    coverage: coverage as Fetched<PlateCoverage>,
  };
};
