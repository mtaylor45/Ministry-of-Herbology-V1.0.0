/** The reads the Specimen page makes, typed against the frozen contract.
 *
 * `$api/client.ts` carries the shapes Morning Rounds needs and belongs to
 * neither J nor I, so the facets' own calls live here instead of being bolted
 * onto a file this parts of the project may not edit. The types below are
 * `contracts/openapi/openapi.yaml` verbatim — where the contract and this file
 * disagree, the contract is right and this file is the bug.
 */

import type { Confidence, FrostAlert, FrostReport, Task } from '$api/client';
import { ApiError, BASE, get, type Fetcher } from '../../shared/http';

export type { Confidence, FrostAlert, FrostReport, Task };

export type SpecimenStatus =
  'thriving' | 'struggling' | 'dormant' | 'overwintering' | 'lost' | 'given_away' | 'archived';

export type EnrichmentState = 'pending' | 'running' | 'complete' | 'failed';

export interface SpeciesBriefRef {
  id: string;
  accepted_name: string;
  common_name: string | null;
  family: string | null;
}

export interface LocationRef {
  id: string;
  name: string;
  kind: string;
  is_outdoor: boolean;
  is_covered: boolean;
  sun_exposure: string | null;
  map_layer_id: string | null;
  specimen_count: number;
}

export interface SpecimenDetail {
  id: string;
  display_name: string;
  nickname: string | null;
  cultivar: string | null;
  species: SpeciesBriefRef | null;
  is_group: boolean;
  count: number;
  location: LocationRef | null;
  map_layer_id: string | null;
  pin_px: { x: number; y: number } | null;
  is_outdoor: boolean;
  in_container: boolean;
  container_litres: number | null;
  soil_note: string | null;
  acquired_on: string | null;
  provenance: string | null;
  status: SpecimenStatus;
  primary_photo_url: string | null;
  created_at: string | null;
}

export interface SourceRef {
  id: string;
  kind: string;
  title: string;
  url: string | null;
  license: string | null;
  retrieved_at: string | null;
}

export interface SpeciesDetail extends SpeciesBriefRef {
  common_names: string[];
  genus: string | null;
  native_range: string[];
  summary: string | null;
  light_label: string | null;
  water_k_c: number | null;
  water_interval_days: number | null;
  soil_ph_min: number | null;
  soil_ph_max: number | null;
  fertilizer_note: string | null;
  humidity_min_pct: number | null;
  min_temp_c: number | null;
  usda_zone_min: string | null;
  usda_zone_max: string | null;
  dormancy_months: number[];
  toxic_to_pets: boolean | null;
  toxic_to_children: boolean | null;
  toxicity_note: string | null;
  enrichment_state: EnrichmentState;
  sources: SourceRef[];
}

export interface CareValue {
  field: string;
  value: unknown;
  unit: string | null;
  source: SourceRef | null;
  confidence: Confidence;
  is_user_override: boolean;
  note: string | null;
}

export interface WaterBalance {
  specimen_id: string;
  deficit_mm: number;
  capacity_mm: number;
  threshold_mm: number;
  k_c: number;
  is_due: boolean;
  sensor_override_pct: number | null;
  days: {
    day: string;
    deficit_mm: number;
    et0_mm: number;
    precip_mm: number;
    irrigation_mm: number;
  }[];
}

export interface CareRule {
  id: string;
  species_id: string | null;
  specimen_id: string | null;
  task_type: string;
  strategy: 'interval' | 'water_balance' | 'frost_guard' | 'seasonal';
  base_interval_days: number | null;
  amount_ml: number | null;
  modifiers: Record<string, unknown>;
  months: number[];
  enabled: boolean;
}

export interface Photo {
  id: string;
  url: string;
  thumb_url: string | null;
  taken_at: string;
  caption: string | null;
  is_primary: boolean;
}

export interface LogEntry {
  id: string;
  kind: 'growth' | 'pest' | 'disease' | 'repot' | 'prune' | 'relocate' | 'note';
  occurred_at: string;
  body: string | null;
  photo: Photo | null;
  data: Record<string, unknown> | null;
}

/** The transport half lives beside the other screens that make these reads, so
 *  the Almanac and the facets fail in the same words. Re-exported here because
 *  this module is still the Specimen page's single import. */
export { ApiError, BASE, get, reason, settle, type Fetched, type Fetcher } from '../../shared/http';

export const reads = {
  specimen: (id: string, f: Fetcher) => get<SpecimenDetail>(`/specimens/${id}`, f),
  species: (id: string, f: Fetcher) => get<SpeciesDetail>(`/species/${id}`, f),
  careValues: (speciesId: string, f: Fetcher) =>
    get<CareValue[]>(`/species/${speciesId}/care-values`, f),
  photos: (id: string, f: Fetcher) => get<Photo[]>(`/specimens/${id}/photos`, f),
  log: (id: string, f: Fetcher) => get<LogEntry[]>(`/specimens/${id}/log`, f),
  tasks: (id: string, f: Fetcher) => get<Task[]>(`/tending/tasks?specimen_id=${id}`, f),
  careRules: (id: string, f: Fetcher) =>
    get<CareRule[]>(`/tending/care-rules?specimen_id=${id}`, f),
  waterBalance: (id: string, f: Fetcher) => get<WaterBalance>(`/almanac/water-balance/${id}`, f),
  frost: (f: Fetcher) => get<FrostReport>('/almanac/frost', f),
};

/** Save a care value the reader has corrected.
 *
 * Two routes, because the contract has two and they mean different things. A
 * specimen override (`PATCH /specimens/{id}`) corrects this plant; a care-value
 * override (`PUT /species/{id}/care-values`) corrects the species for every
 * plant of it. Correcting one plant is what a keeper almost always means, so
 * that route is preferred wherever the contract offers it.
 */
export async function saveCareValue(
  target:
    | { route: 'specimen'; id: string; overrideField: string }
    | { route: 'species'; id: string; field: string },
  value: number | string | boolean | null,
  fetcher: Fetcher,
): Promise<void> {
  const [path, method, body] =
    target.route === 'specimen'
      ? [`/specimens/${target.id}`, 'PATCH', { [target.overrideField]: value }]
      : [`/species/${target.id}/care-values`, 'PUT', { field: target.field, value }];

  const response = await fetcher(`${BASE}${path}`, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
}
