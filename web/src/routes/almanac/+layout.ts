/** Which site the Almanac is about, resolved once for all three views.
 *
 * `GET /almanac/forecast` requires a `site_id` and the contract has no endpoint
 * that lists sites, so it is read off a location (`siteIdFrom`). Doing it in the
 * layout means the three views share one request and one failure.
 */

import { reads, settle, siteIdFrom, type AlmanacLocation } from './api';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ fetch }) => {
  const locations = await settle(reads.locations(fetch));
  const value: AlmanacLocation[] = locations.value ?? [];
  return {
    locations: value,
    locationsError: locations.error,
    siteId: siteIdFrom(value),
  };
};
