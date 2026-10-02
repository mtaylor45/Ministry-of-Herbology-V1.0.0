/** Tending's own reads: the schedule, the water balance and the frost lookahead.
 *
 *  Each is settled separately. A frost lookahead that times out costs the
 *  reader the frost panel and nothing else — a blank Tending page because one
 *  of four endpoints was slow is worse than a page that says which part is
 *  missing.
 */

import type { PageLoad } from './$types';
import {
  reads,
  settle,
  type CareRule,
  type FrostReport,
  type Task,
  type WaterBalance,
} from '../api';

export const load: PageLoad = async ({ params, fetch, depends }) => {
  depends('moh:specimen');
  const [tasks, rules, water, frost] = await Promise.all([
    settle<Task[]>(reads.tasks(params.id, fetch)),
    settle<CareRule[]>(reads.careRules(params.id, fetch)),
    settle<WaterBalance>(reads.waterBalance(params.id, fetch)),
    settle<FrostReport>(reads.frost(fetch)),
  ]);
  return { tasks, rules, water, frost };
};
