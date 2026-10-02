import type { PageLoad } from './$types';
import { reads, settle } from './rounds/api';
import { isRelocation } from './rounds/relocation';

/**
 * Morning Rounds' reads.
 *
 * The round itself is the screen: if it fails there is nothing to show and the
 * page says so. The member picker is a furnishing, and it must not cost the
 * reader their round when the round is the one thing they came outside with.
 *
 * The register is read when the round names a plant it could not schedule —
 * because `unscheduled[]` carries a bare `specimen_id` and a uuid is not a name
 * — and, when the round holds a job that moves a plant: a
 * `bring_indoors` completion should remember where the plant was standing, and
 * the specimen's `location` is the only place that is written down while it is
 * still true. Both are a second round trip on the days they happen and no
 * request at all on the days they do not.
 *
 * The locations list is read for the same reason and under the same condition.
 * It is what the relocation sheet offers, and asking for it on a round with
 * nothing to move would be a request nobody needs.
 *
 * `depends` is what a completion invalidates, so ticking a task off re-reads
 * the round rather than editing a list in the browser and hoping it matches.
 */
export const load: PageLoad = async ({ fetch, depends }) => {
  depends('moh:rounds');
  const [rounds, members] = await Promise.all([
    settle(reads.rounds(fetch)),
    settle(reads.members(fetch)),
  ]);

  const moves = (rounds.value?.due ?? []).some(isRelocation);
  const needsRegister = Boolean(rounds.value?.unscheduled?.length) || moves;

  const [specimens, locations] = await Promise.all([
    needsRegister ? settle(reads.specimens(fetch)) : Promise.resolve(null),
    moves ? settle(reads.locations(fetch)) : Promise.resolve(null),
  ]);

  return { rounds, members, specimens, locations };
};
