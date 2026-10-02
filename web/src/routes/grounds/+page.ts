/** What `/grounds` needs: the sheets, the pins on them, the drawn zones, and
 *  the Register.
 *
 *  Four reads, each settled on its own, because they fail for different reasons
 *  and cost different things. No layers means no screen; no pins means the
 *  screen would be lying if it drew a sheet and said nothing was on it; no
 *  zones costs an overlay; no Register costs the ability to place a plant that
 *  has never been pinned — see `roster.ts` for why that read is here at all.
 */

import { listLayers, listPins, listZones, type MapLayer, type Pin, type Zone } from '$map';
import { settle } from '../shared/http';
import { readRoster, type Roster } from './roster';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const [layers, pins, zones, register] = await Promise.all([
    settle<MapLayer[]>(listLayers(fetch)),
    settle<Pin[]>(listPins(undefined, fetch)),
    settle<Zone[]>(listZones(undefined, fetch)),
    settle<Roster>(readRoster(fetch)),
  ]);

  return {
    layers,
    pins,
    zones,
    register,
    /** `?layer=` — which sheet to open. */
    wantedLayerId: url.searchParams.get('layer'),
    /** `?specimen=` — who sent us here, so the map can say where it is. */
    fromSpecimenId: url.searchParams.get('specimen'),
  };
};
