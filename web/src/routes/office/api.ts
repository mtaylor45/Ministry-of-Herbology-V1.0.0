/** What the Ministry Office reads and writes, against contract 1.7.0.
 *
 *  Calendar feeds are read **in the browser only**, never in `load`. A
 *  universal `load` that fetches during server rendering has its responses
 *  inlined into the page so the browser can replay them — which would put
 *  every feed's URL, token and all, into the HTML of the Office. `readFeeds()`
 *  strips the URLs from the response before returning it, so the only copy of
 *  a listed feed's URL is the response body the browser discards.
 */

import { ApiError, BASE, get, reason, type Fetcher } from '../shared/http';
import type { Member } from '$ui';
import {
  createdFeed,
  listedFeed,
  type CalendarFeedResponse,
  type CalendarFilters,
  type CreatedFeed,
  type Integration,
  type ListedFeed,
} from './office';
import type { RegisterLocation } from '../register/register';

export { reason, settle, type Fetched } from '../shared/http';

/** Integrations, or the plain reason there are none to show. A 404 is its own
 *  state: the hub's route is not served by this API yet, which is a fact about
 *  the deployment, not a failure of the hub. */
export type IntegrationsRead =
  | { state: 'ok'; rows: Integration[] }
  | { state: 'not-served' }
  | { state: 'failed'; reason: string };

export async function readIntegrations(f: Fetcher): Promise<IntegrationsRead> {
  try {
    return { state: 'ok', rows: await get<Integration[]>('/hub/integrations', f) };
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return { state: 'not-served' };
    return { state: 'failed', reason: reason(cause) };
  }
}

export const reads = {
  members: (f: Fetcher) => get<Member[]>('/members', f),
  locations: (f: Fetcher) => get<RegisterLocation[]>('/locations', f),
};

/** `no-store`, so the browser's own HTTP cache does not keep a response that
 *  has every feed's URL in it on disk. */
export async function readFeeds(f: Fetcher): Promise<ListedFeed[]> {
  const path = '/tending/feeds';
  const response = await f(`${BASE}${path}`, {
    headers: { accept: 'application/json' },
    cache: 'no-store',
  });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
  const raw = (await response.json()) as CalendarFeedResponse[];
  return raw.map(listedFeed);
}

export async function createFeed(
  body: { member_id: string; name: string; filters: CalendarFilters },
  f: Fetcher,
): Promise<CreatedFeed> {
  const path = '/tending/feeds';
  const response = await f(`${BASE}${path}`, {
    method: 'POST',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
  return createdFeed((await response.json()) as CalendarFeedResponse);
}

/** Revoke one feed. `204`, no body, so `post()` (which reads JSON) is not used. */
export async function revokeFeed(id: string, f: Fetcher): Promise<void> {
  const path = `/tending/feeds/${encodeURIComponent(id)}/revoke`;
  const response = await f(`${BASE}${path}`, { method: 'POST' });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
}
