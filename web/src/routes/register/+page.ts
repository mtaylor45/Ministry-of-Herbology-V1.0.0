import type { PageLoad } from './$types';
import { reads, settle } from './api';
import { parseFilters } from './register';

/**
 * The Register's reads. The filters come from the address and nowhere else, so
 * a bookmark, a shared link and the back button all land on the same list.
 *
 * The list is the screen; the locations and the species list are furnishings.
 * Each settles on its own, so a failed species read costs the rows their
 * toxicity mark (and they say so) rather than costing the reader the Register.
 */
export const load: PageLoad = async ({ fetch, url, depends }) => {
  depends('moh:register');
  const filters = parseFilters(url.searchParams);
  const [page, locations, species] = await Promise.all([
    settle(reads.specimens(filters, null, fetch)),
    settle(reads.locations(fetch)),
    settle(reads.species(fetch)),
  ]);
  return {
    filters,
    page,
    locations,
    species,
  };
};
