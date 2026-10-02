/** The Register entry's own reads: the photographs, the growth log, and the map.
 *
 *  The first two are the inventory API's and answer `[]` until their an earlier release work lands,
 *  so the facet shows an empty log honestly rather than hiding the panel.
 *
 *  The map reads are new and are what lets this facet say *where* the
 *  plant is. They are settled separately from each other and from the rest:
 *  the Grounds being unreachable must cost this page one panel's worth of
 *  certainty and nothing else, and — this is the part worth saying out loud —
 *  it must not be mistaken for "this plant has no pin". See `mapPlace.ts`.
 */

import { listLayers, listPins, type MapLayer, type Pin } from '$map';
import type { PageLoad } from './$types';
import { reads, settle, type LogEntry, type Photo } from '../api';

export const load: PageLoad = async ({ params, fetch, depends }) => {
  depends('moh:specimen');
  const [photos, log, layers, pins] = await Promise.all([
    settle<Photo[]>(reads.photos(params.id, fetch)),
    settle<LogEntry[]>(reads.log(params.id, fetch)),
    settle<MapLayer[]>(listLayers(fetch)),
    // Unfiltered: `GET /grounds/pins` takes a `layer_id` and this page does not
    // reliably know one — in mock mode the specimen record's own
    // `map_layer_id` is always null while the Grounds holds a real pin. A
    // household's worth of pins is a short list.
    settle<Pin[]>(listPins(undefined, fetch)),
  ]);
  return { photos, log, layers, pins };
};
