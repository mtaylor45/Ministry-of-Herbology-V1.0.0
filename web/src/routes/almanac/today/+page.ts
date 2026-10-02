/** Today, hour by hour. Same endpoint as the ten days, hourly horizon. */

import { reads, settle, type Fetched, type ForecastPoint } from '../api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, parent }) => {
  const { siteId } = await parent();
  const forecast: Fetched<ForecastPoint[]> = siteId
    ? await settle(reads.forecast(siteId, 'hourly', fetch))
    : { value: null, error: 'No site is recorded, so there is nowhere to forecast for.' };
  return { forecast };
};
