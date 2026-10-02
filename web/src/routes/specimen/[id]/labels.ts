/** Themed words and the plain ones they travel with.
 *
 * Nothing here renders on its own: every entry is a pair, and the components
 * that take them refuse to show the themed half alone.
 */

import { STATUS, type Status } from '$ui';
import type { EnrichmentState, SpecimenStatus } from './api';

// Shared with Morning Rounds, which reads the same task types off the same
// endpoint. Re-exported so this screen's imports do not have to move.
export { TASK_TYPES, formatDate, taskTypeLabel } from '../../shared/labels';

/** The Register's status vocabulary. Three of the seven already live in `$ui`;
 *  the other four are this screen's, paired the same way. */
const EXTRA_STATUSES: Record<string, Status> = {
  overwintering: {
    themed: 'Wintering indoors',
    plain: 'Overwintering — brought in for the cold',
    tone: 'frost',
  },
  lost: { themed: 'Lost to us', plain: 'Died or was lost', tone: 'ailing' },
  given_away: { themed: 'Passed to another keeper', plain: 'Given away', tone: 'sated' },
  archived: {
    themed: 'Struck from the Register',
    plain: 'Archived — kept as a record',
    tone: 'sated',
  },
};

export function specimenStatus(status: SpecimenStatus | string): Status {
  switch (status) {
    case 'thriving':
      return STATUS.thriving;
    case 'struggling':
      return STATUS.struggling;
    case 'dormant':
      return STATUS.dormant;
    default:
      return (
        EXTRA_STATUSES[status] ?? {
          themed: 'Unrecorded',
          plain: `Status "${status}" is not one the app knows`,
          tone: 'ailing',
        }
      );
  }
}

export const SUN_EXPOSURE: Record<string, string> = {
  full_sun: 'Full sun',
  part_sun: 'Part sun',
  part_shade: 'Part shade',
  full_shade: 'Full shade',
  unknown: 'Sun exposure not recorded',
};

export const LOCATION_KIND: Record<string, string> = {
  area: 'Area',
  zone: 'Zone',
  bed: 'Bed',
  room: 'Room',
  shelf: 'Shelf',
};

export const LOG_KINDS: Record<string, { themed: string; plain: string }> = {
  growth: { themed: 'Growth observed', plain: 'Growth note' },
  pest: { themed: 'Infestation', plain: 'Pest' },
  disease: { themed: 'Affliction', plain: 'Disease' },
  repot: { themed: 'Rehoused', plain: 'Repotted' },
  prune: { themed: 'Pruned back', plain: 'Pruned' },
  relocate: { themed: 'Moved house', plain: 'Moved to another location' },
  note: { themed: 'Marginalia', plain: 'Note' },
};

export const CARE_STRATEGIES: Record<string, { themed: string; plain: string }> = {
  interval: { themed: 'By the calendar', plain: 'Fixed interval between waterings' },
  water_balance: {
    themed: 'By rain and sun',
    plain: 'Soil water balance — rainfall against evaporation',
  },
  frost_guard: { themed: 'Against the frost', plain: 'Frost guard — triggered by the forecast' },
  seasonal: { themed: 'By the season', plain: 'Seasonal adjustment' },
};

/** What the enrichment queue is doing, said honestly.
 *
 *  The brief's rule: an honest progress state, never a spinner that lies about
 *  being finished. `pending` and `running` are told apart because a queued job
 *  and a job in flight are different things to be waiting on, and `failed` says
 *  so outright instead of leaving the page to look merely empty. */
export interface EnrichmentProgress {
  state: EnrichmentState | 'unidentified';
  themed: string;
  plain: string;
  /** True while more is expected to arrive without the reader doing anything. */
  busy: boolean;
}

export function enrichmentProgress(
  state: EnrichmentState | null | undefined,
  hasSpecies: boolean,
): EnrichmentProgress {
  if (!hasSpecies) {
    return {
      state: 'unidentified',
      themed: 'No name yet set down',
      plain: 'This plant has not been matched to a species, so there is nothing to look up.',
      busy: false,
    };
  }
  switch (state) {
    case 'pending':
      return {
        state: 'pending',
        themed: 'An owl has been dispatched…',
        plain: 'Looking this plant up. Values appear below as each source answers.',
        busy: true,
      };
    case 'running':
      return {
        state: 'running',
        themed: 'The owl is abroad…',
        plain: 'Reading the sources now. Values appear below as each one answers.',
        busy: true,
      };
    case 'failed':
      return {
        state: 'failed',
        themed: 'The owl returned empty-handed',
        plain:
          'The lookup failed. What is shown below is all that was gathered — nothing was invented to fill the gaps.',
        busy: false,
      };
    case 'complete':
    default:
      return {
        state: 'complete',
        themed: 'The owl is home',
        plain: 'Lookup finished. Every value below carries the source it came from.',
        busy: false,
      };
  }
}
