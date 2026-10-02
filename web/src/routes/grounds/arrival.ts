/** Arriving at the map from somewhere else.
 *
 * The earlier exit criterion runs both ways. The maps module built the half that starts on the
 * map: every pin is a real anchor to `/specimen/{id}/register`. This module is
 * the other half's landing — what `/grounds` has to work out when a Specimen
 * page sent somebody here, which is two questions and not one:
 *
 *   1. **Which sheet should be open?** The map component picks the first
 *      layer it is given, so the route answers this by ordering the layers it
 *      passes rather than by reaching into the component.
 *   2. **Did the plant that sent me here actually make it onto a sheet?** A
 *      link that lands you on the right plan and says nothing has failed the
 *      person holding the phone, because the one thing they came to see is a
 *      pin among several that all look alike.
 *
 * Both answers are pure functions of the layers and pins the load already
 * fetched, so they are tested without a browser and the page is a renderer.
 */

import { displayName, positionSentence, type MapLayer, type Pin } from '$map';

/** Where the plant that sent us here stands, in words, for a line above the map. */
export interface Arrival {
  specimenId: string;
  name: string;
  /** The sheet to open: the layer its pin is on, when it has one. */
  layerId: string | null;
  /** Plain sentence. Never coordinates — see `pins.ts` for why. */
  sentence: string;
  /** Back to the page that sent us, so the cross-link is a round trip. */
  backHref: string;
  /** True once there is a pin on a sheet. False is a normal state, not an error. */
  placed: boolean;
}

/** The Specimen page a pin opens, and the page that links back to the map.
 *
 *  Deliberately the same shape the maps module's `specimenHref` builds: the Register facet is
 *  where a plant's place is written down, so both directions of the cross-link
 *  land on the same facet rather than on two different ones. */
export function specimenBackHref(specimenId: string): string {
  return `/specimen/${specimenId}/register`;
}

/** What to say about the plant named in `?specimen=`, or `null` if none was.
 *
 * The three outcomes are the three honest states, and the second two are not
 * failures: a plant can be in the Register with no pin, and the map can be
 * asked about a plant it has never heard of (a link kept open while somebody
 * deleted the plant, most likely).
 */
export function arrival(
  specimenId: string | null,
  layers: readonly MapLayer[],
  pins: readonly Pin[],
  registerWasRead = true,
): Arrival | null {
  if (!specimenId) return null;

  const backHref = specimenBackHref(specimenId);
  const pin = pins.find((candidate) => candidate.specimen_id === specimenId) ?? null;
  const name = pin ? displayName(pin) : 'That plant';

  if (!pin) {
    // With the Register in hand, `roster.ts` has already put a placeable row
    // here for every plant that exists, so no row means no plant. Without it,
    // the honest answer is that this screen cannot tell.
    return {
      specimenId,
      name,
      layerId: null,
      sentence: registerWasRead
        ? 'Neither the map nor the Register lists that plant. It may have been removed since the link was made.'
        : 'The Register could not be read, so this screen cannot say whether that plant has a place on a plan.',
      backHref,
      placed: false,
    };
  }

  const layer = layers.find((candidate) => candidate.id === pin.layer_id) ?? null;

  if (!layer) {
    return {
      specimenId,
      name,
      layerId: null,
      sentence: `${name} is pinned to a plan this deployment no longer holds. Place it again on one of the plans below.`,
      backHref,
      placed: false,
    };
  }

  if (!pin.px) {
    return {
      specimenId,
      name,
      layerId: layer.id,
      sentence: `${name} is not placed on ${layer.name} yet. It is in the list below the map — choose “Place” and the arrow keys or a tap will put it down.`,
      backHref,
      placed: false,
    };
  }

  return {
    specimenId,
    name,
    layerId: layer.id,
    // The maps module's sentence, unchanged: it already says where on the sheet, and already
    // says so without distances when the sheet has no scale.
    sentence: `${name} is here — ${lowerFirst(positionSentence(layer, pin.px))}`,
    backHref,
    placed: true,
  };
}

/** The layers to hand the map, with the wanted one first.
 *
 * `Grounds` opens `layers[0]` and exposes no prop for which layer is active,
 * so this is the route's only contract-legal lever on where a link lands — and
 * it is a fair one: the switcher still lists every layer, and ordering the
 * list the route passes is the route's business. Escalated to the maps module in the PR
 * body: an `activeLayerId` prop on `Grounds` would be one line and would make
 * this function unnecessary.
 *
 * The order is otherwise left exactly as the API served it (stacking order),
 * because that is the maps module's meaning for it and not this route's to re-sort.
 */
export function orderLayers(layers: readonly MapLayer[], wantedId: string | null): MapLayer[] {
  if (!wantedId) return [...layers];
  const wanted = layers.filter((layer) => layer.id === wantedId);
  if (wanted.length === 0) return [...layers];
  return [...wanted, ...layers.filter((layer) => layer.id !== wantedId)];
}

function lowerFirst(sentence: string): string {
  return sentence.charAt(0).toLowerCase() + sentence.slice(1);
}
