/** Where this plant is on the map, and the honest answer when it is nowhere.
 *
 * The maps module's half of the earlier cross-link runs from the map to the plant: every pin is a
 * real anchor to this page. This module is the other direction — the plant
 * saying *where it is* and offering the way there — and the whole difficulty
 * is that "where it is" has more than one true answer:
 *
 *   - it is pinned to a sheet that has a scale, so the position can be given
 *     in metres;
 *   - it is pinned to a sheet nobody has calibrated, so there is a place but
 *     no distance, and inventing one would be a plant fact with no source
 *;
 *   - the map knows the plant and holds no position for it;
 *   - the Register knows where it stands and the map has no sheet for that
 *     place, or no sheets at all;
 *   - the reads failed, and the screen must say so rather than claim the plant
 *     is unpinned.
 *
 * Each of those is a different sentence and a different next action, so each
 * is a named state rather than a truthy check. The caveat travels *with* the
 * sentence and the link.
 *
 * **Two records, one truth.** `GET /specimens/{id}` carries `map_layer_id` and
 * `pin_px`, and `GET /grounds/pins` carries the same two facts — in the live
 * deployment they are literally the same two columns. In mock mode they are
 * not: The maps module's Grounds is a writable store and the inventory API's fixture repository serves a
 * static `pin_px: null`, so a pin placed on the map would be invisible here if
 * this page trusted the specimen record alone. The Grounds is therefore
 * preferred where both answer, because it is the record the map writes, and
 * the specimen's own columns are the fallback for when `/grounds` cannot be
 * read at all.
 */

import { isCalibrated, positionSentence, type MapLayer, type Pin, type PixelPoint } from '$map';
import type { SpecimenDetail } from './api';

export type PlaceState =
  /** Pinned, and the sheet has a measure, so the position is given in metres. */
  | 'pinned'
  /** Pinned to a sheet with no scale: a place, and honestly no distance. */
  | 'pinned_without_scale'
  /** The map holds the plant against a sheet but has no position for it. */
  | 'awaiting_pin'
  /** No pin, but the place it stands in has a plan — so there is a sheet to go to. */
  | 'place_has_a_plan'
  /** Its place is recorded and no plan covers that place. */
  | 'place_has_no_plan'
  /** No plans are lodged at all. */
  | 'no_plans'
  /** Nothing connects this plant to a sheet, and its place is not recorded. */
  | 'unplaced'
  /** The map could not be read. Not the same as "not pinned". */
  | 'unknown';

export interface Place {
  state: PlaceState;
  /** Whether a pin exists. Drives nothing but the wording; kept explicit. */
  placed: boolean;
  /** The sheet in question, when one is known. */
  layer: MapLayer | null;
  /** What is true, in plain words. Never coordinates. */
  sentence: string;
  /** The limit on what was just said, or `null` when there is none. */
  caveat: string | null;
  /** Where the link goes. Always somewhere: the map is reachable regardless. */
  href: string;
  linkThemed: string;
  linkPlain: string;
}

/** The link that carries this plant's identity to the map. */
export function groundsHref(specimenId: string, layerId: string | null): string {
  const query = new URLSearchParams({ specimen: specimenId });
  if (layerId) query.set('layer', layerId);
  return `/grounds?${query.toString()}`;
}

interface Resolved {
  layerId: string;
  px: PixelPoint | null;
  /** Which record answered: the map's own, or the specimen row. */
  source: 'grounds' | 'specimen';
}

/** The pin, from whichever record holds one. See the module note on precedence. */
function resolvePin(specimen: SpecimenDetail, pins: readonly Pin[] | null): Resolved | null {
  const fromGrounds = pins?.find((pin) => pin.specimen_id === specimen.id) ?? null;
  if (fromGrounds) {
    return { layerId: fromGrounds.layer_id, px: fromGrounds.px, source: 'grounds' };
  }
  if (specimen.map_layer_id) {
    return { layerId: specimen.map_layer_id, px: specimen.pin_px, source: 'specimen' };
  }
  return null;
}

/** Where this plant is, as a sentence, a caveat and a link.
 *
 * `layers` or `pins` being `null` means that read failed — which is a state of
 * its own and not an absence of pins.
 */
export function place(
  specimen: SpecimenDetail,
  layers: readonly MapLayer[] | null,
  pins: readonly Pin[] | null,
  readFailure: string | null = null,
): Place {
  const openTheMap = { linkThemed: 'The Grounds', linkPlain: 'Open the map' };

  if (layers === null || pins === null) {
    return {
      state: 'unknown',
      placed: false,
      layer: null,
      sentence: 'Whether this plant is on a plan could not be checked.',
      caveat:
        readFailure ??
        'The Grounds did not answer, so this says nothing either way — it is not a claim that the plant is unpinned.',
      href: groundsHref(specimen.id, specimen.map_layer_id),
      ...openTheMap,
    };
  }

  const pin = resolvePin(specimen, pins);
  const layer = pin ? (layers.find((candidate) => candidate.id === pin.layerId) ?? null) : null;

  if (pin && layer && pin.px) {
    const calibrated = isCalibrated(layer.kind, layer.calibration);
    return {
      state: calibrated ? 'pinned' : 'pinned_without_scale',
      placed: true,
      layer,
      // The maps module's own sentence, which already names the part of the sheet and
      // already declines to give a distance when the sheet has no measure.
      // Capitalised because here it stands alone as a paragraph, where in the maps module's
      // list it follows the plant's name.
      sentence: capitaliseFirst(positionSentence(layer, pin.px)),
      // The maps module's sentence already says the sheet is uncalibrated. What it cannot
      // say is what to do about it, so that is all this adds — the caveat and
      // the remedy in the same breath, rather than the same fact twice.
      caveat: calibrated
        ? null
        : `Calibrating ${layer.name} on The Grounds turns that into a distance, and re-places every pin on it against the new measure.`,
      href: groundsHref(specimen.id, layer.id),
      linkThemed: 'The Grounds',
      linkPlain: `See it on ${layer.name}`,
    };
  }

  if (pin && layer && !pin.px) {
    return {
      state: 'awaiting_pin',
      placed: false,
      layer,
      sentence: `Listed against ${layer.name} and not yet placed on it.`,
      caveat: `The plan knows this plant belongs on it. Choose “Place” beside its name on The Grounds and a tap, or the arrow keys, puts the pin down.`,
      href: groundsHref(specimen.id, layer.id),
      linkThemed: 'The Grounds',
      linkPlain: `Place it on ${layer.name}`,
    };
  }

  if (layers.length === 0) {
    return {
      state: 'no_plans',
      placed: false,
      layer: null,
      sentence: 'No plan or survey is lodged yet, so there is nowhere to pin this plant.',
      caveat:
        'Upload a floor plan or a property survey on The Grounds and every plant in the Register can be placed on it.',
      href: groundsHref(specimen.id, null),
      linkThemed: 'The Grounds',
      linkPlain: 'Upload a plan',
    };
  }

  const placeLayerId = specimen.location?.map_layer_id ?? null;
  const placeLayer = placeLayerId
    ? (layers.find((candidate) => candidate.id === placeLayerId) ?? null)
    : null;

  if (specimen.location && placeLayer) {
    return {
      state: 'place_has_a_plan',
      placed: false,
      layer: placeLayer,
      sentence: `The Register has it in ${specimen.location.name}, which is drawn on ${placeLayer.name}. The map holds no pin for this plant.`,
      caveat:
        'A location is a place with a name; a pin is a spot on a sheet. This plant has the first and not the second, so it does not appear on the map.',
      href: groundsHref(specimen.id, placeLayer.id),
      linkThemed: 'The Grounds',
      linkPlain: `Place it on ${placeLayer.name}`,
    };
  }

  if (specimen.location) {
    return {
      state: 'place_has_no_plan',
      placed: false,
      layer: null,
      sentence: `The Register has it in ${specimen.location.name}, and no plan covers that place yet.`,
      caveat:
        'It can still be pinned to any plan that is lodged — a pin is a spot on a sheet, and the sheet need not be the one the location names.',
      href: groundsHref(specimen.id, null),
      ...openTheMap,
    };
  }

  return {
    state: 'unplaced',
    placed: false,
    layer: null,
    sentence: 'Not on any plan, and no location is recorded for it either.',
    caveat:
      'Either will do: give it a location in the Register, or pin it straight onto a plan on The Grounds.',
    href: groundsHref(specimen.id, null),
    ...openTheMap,
  };
}

function capitaliseFirst(sentence: string): string {
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}
