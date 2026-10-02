/** What every facet of the Specimen page needs: the plant, its species, and
 *  the cited care values.
 *
 *  Loading these once in the layout is what makes the facets cross-link
 *  cheaply — moving between Register, Tending and Compendium re-runs only the
 *  facet's own reads, not the plant's.
 */

import { error } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';
import { ApiError, reads, settle, type CareValue, type Fetched, type SpeciesDetail } from './api';

export const load: LayoutLoad = async ({ params, fetch, depends }) => {
  // Enrichment lands in the background, so the page needs a handle to re-read
  // itself with. See `+layout.svelte`.
  depends('moh:specimen');

  let specimen;
  try {
    specimen = await reads.specimen(params.id, fetch);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      error(404, 'No plant in the Register has that number.');
    }
    throw cause;
  }

  const speciesId = specimen.species?.id ?? null;
  if (!speciesId) {
    // An unmatched plant is a real state, not an error: the Register accepts a
    // typed name before the botany worker has resolved it.
    const noSpecies: Fetched<SpeciesDetail | null> = { value: null, error: null };
    const noValues: Fetched<CareValue[]> = { value: [], error: null };
    return { specimen, speciesId, species: noSpecies, careValues: noValues };
  }

  const [species, careValues] = await Promise.all([
    settle<SpeciesDetail | null>(reads.species(speciesId, fetch)),
    settle<CareValue[]>(reads.careValues(speciesId, fetch)),
  ]);

  return { specimen, speciesId, species, careValues };
};
