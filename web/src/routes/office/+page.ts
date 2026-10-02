import type { PageLoad } from './$types';
import { readIntegrations, reads, settle } from './api';

/**
 * The Office's reads, each settled on its own so one failing costs its
 * section and nothing else.
 *
 * Calendar feeds are deliberately **not** read here — see `api.ts`: a feed
 * read during server rendering would be inlined into the page, URLs included.
 * The feeds section reads them in the browser after it mounts.
 */
export const load: PageLoad = async ({ fetch, depends }) => {
  depends('moh:office');
  const [integrations, members, locations] = await Promise.all([
    readIntegrations(fetch),
    settle(reads.members(fetch)),
    settle(reads.locations(fetch)),
  ]);
  return { integrations, members, locations };
};
