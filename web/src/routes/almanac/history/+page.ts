/** The conditions record, indoors against outdoors.
 *
 * Both series are asked for in parallel and settled separately: the indoor
 * record failing must cost the reader the indoor line and nothing else.
 */

import {
  indoorLocations,
  reads,
  settle,
  type AlmanacLocation,
  type Fetched,
  type Series,
} from '../api';
import { OUTDOOR_ONLY, parseMetric, parseWindow } from '../history';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, parent, url }) => {
  const { siteId, locations } = await parent();
  const window = parseWindow(url.searchParams.get('window'));
  const metric = parseMetric(url.searchParams.get('metric'));

  const indoors = indoorLocations(locations);
  const asked = url.searchParams.get('location');
  const room: AlmanacLocation | null =
    indoors.find((location) => location.id === asked) ?? indoors[0] ?? null;

  const outdoorWork: Promise<Fetched<Series>> = siteId
    ? settle(reads.history({ window, metric, siteId }, fetch))
    : Promise.resolve({
        value: null,
        error: 'No site is recorded, so there is no weather record.',
      });

  // Rain and evaporation describe the sky, not a room: asking for them by
  // location is asking a question the rollups cannot answer.
  const indoorWork: Promise<Fetched<Series> | null> =
    room && !OUTDOOR_ONLY.includes(metric)
      ? settle(reads.history({ window, metric, locationId: room.id }, fetch))
      : Promise.resolve(null);

  const [outdoor, indoor] = await Promise.all([outdoorWork, indoorWork]);

  return { window, metric, room, indoors, outdoor, indoor };
};
