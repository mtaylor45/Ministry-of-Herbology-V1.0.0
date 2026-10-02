/** The add-a-plant form's decisions, kept out of the component so they can be
 *  tested: how a candidate is described, whether it is a species the household
 *  already has, and what `POST /specimens` is sent. */

import type { SpecimenCreate, SpeciesRow, TaxonCandidate } from './api';

const CONFIDENCE: Record<string, string> = {
  high: 'high confidence',
  medium: 'medium confidence',
  low: 'low confidence',
  unknown: 'confidence unknown',
};

/** One candidate, in words: the name, what people call it, its family, how
 *  sure the source is and which source it was. */
export function candidateLabel(candidate: TaxonCandidate): string {
  const parts = [candidate.accepted_name];
  if (candidate.cultivar) parts[0] += ` ‘${candidate.cultivar}’`;
  if (candidate.common_name) parts.push(candidate.common_name);
  if (candidate.family) parts.push(candidate.family);
  const sure = CONFIDENCE[candidate.confidence] ?? CONFIDENCE.unknown;
  const source = candidate.source?.title ? ` (${candidate.source.title})` : '';
  return `${parts.join(' · ')} — ${sure}${source}`;
}

/** The household's existing species with this accepted name, if any. */
export function knownSpeciesId(
  candidate: TaxonCandidate,
  species: readonly SpeciesRow[],
): string | null {
  const wanted = candidate.accepted_name.trim().toLowerCase();
  return species.find((s) => s.accepted_name.trim().toLowerCase() === wanted)?.id ?? null;
}

/** What `POST /specimens` is sent. Optional fields are left out rather than
 *  sent empty, so the server's own defaults apply. */
export function createBody(input: {
  typed: string;
  candidate: TaxonCandidate | null;
  speciesId: string | null;
  nickname: string;
  locationId: string;
  count: number | null;
}): SpecimenCreate {
  const body: SpecimenCreate = {
    name: input.candidate ? input.candidate.accepted_name : input.typed.trim(),
  };
  if (input.speciesId) body.species_id = input.speciesId;
  if (input.candidate?.cultivar) body.cultivar = input.candidate.cultivar;
  const nickname = input.nickname.trim();
  if (nickname) body.nickname = nickname;
  if (input.locationId) body.location_id = input.locationId;
  if (input.count && input.count > 1) body.count = Math.floor(input.count);
  return body;
}
