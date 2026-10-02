/** What the Register reads and writes, against contract 1.7.0.
 *
 *  `GET /specimens` is the list. `GET /locations` names the location filter.
 *  `GET /species` is read once for the toxicity mark on each row, because
 *  `Specimen` does not carry toxicity and `Species` does; a household's species
 *  list is short, and one read beats one per row. Adding a plant goes through
 *  The botany worker's `POST /taxon/resolve` before the inventory API's `POST /specimens`, so the person picks
 *  the species rather than the server guessing from a typed name.
 */

import { get, post, type Fetcher } from '../shared/http';
import type {
  RegisterLocation,
  RegisterSpecimen,
  RegisterFilters,
  SpeciesToxicity,
  SpecimenPage,
} from './register';
import { specimensPath } from './register';

export { reason, settle, type Fetched, type Fetcher } from '../shared/http';

/** `TaxonCandidate`. */
export interface TaxonCandidate {
  accepted_name: string;
  common_name?: string | null;
  cultivar?: string | null;
  family?: string | null;
  rank?: string;
  score?: number;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  source?: { title?: string; url?: string | null } | null;
}

/** `SpecimenCreate`. */
export interface SpecimenCreate {
  name: string;
  species_id?: string;
  nickname?: string;
  cultivar?: string;
  location_id?: string;
  in_container?: boolean;
  count?: number;
}

/** A `Species` row, narrowed to what the add form and the toxicity mark read. */
export interface SpeciesRow extends SpeciesToxicity {
  accepted_name: string;
  common_name?: string | null;
}

export const reads = {
  specimens: (filters: RegisterFilters, cursor: string | null, f: Fetcher) =>
    get<SpecimenPage>(specimensPath(filters, cursor), f),
  locations: (f: Fetcher) => get<RegisterLocation[]>('/locations', f),
  species: (f: Fetcher) => get<SpeciesRow[]>('/species', f),
};

export const writes = {
  resolve: (name: string, f: Fetcher) => post<TaxonCandidate[]>('/taxon/resolve', { name }, f),
  create: (body: SpecimenCreate, f: Fetcher) => post<RegisterSpecimen>('/specimens', body, f),
};
