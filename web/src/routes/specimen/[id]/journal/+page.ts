/** The journal facet's own reads: the plates, this plant's field notes, the
 *  household (to name who accepts a plate), and the photo growth log.
 *
 *  The first three are the journal's reads, imported from the journal's `api.ts` rather
 *  than copied — the plate and the notes are the journal's feature, rendered here
 *  because this is where a person stands when they want to see their plant's
 *  plate. The photographs are this parts of the project's read against the inventory API's route.
 *
 *  Each settles separately. A plate that cannot be fetched costs the reader
 *  the plate and nothing else: the field notes and the growth log still show,
 *  and the plate panel says what went wrong rather than reading as "no plate".
 */

import type { PageLoad } from './$types';
import {
  reads as journalReads,
  type FieldNote,
  type Member,
  type Plate,
} from '../../../journal/api';
import { reads, settle, type Photo } from '../api';

export const load: PageLoad = async ({ params, fetch, depends }) => {
  depends('moh:specimen');
  const [plates, notes, members, photos] = await Promise.all([
    settle<Plate[]>(journalReads.plates(fetch)),
    settle<FieldNote[]>(journalReads.notes(params.id, fetch)),
    settle<Member[]>(journalReads.members(fetch)),
    settle<Photo[]>(reads.photos(params.id, fetch)),
  ]);
  return { plates, notes, members, photos };
};
