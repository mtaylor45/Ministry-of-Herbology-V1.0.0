/** Completing a task that moves a plant.
 *
 * an earlier release is the frost guard, and the frost guard's whole point is that a plant ends
 * up somewhere else. `POST /tending/tasks/{id}/complete` takes
 * `new_location_id` — *"Set when completing a bring_indoors task"* — and
 * The scheduler performs the move through the inventory API before it ticks anything
 * off. This module is the screen's half of that: which tasks move a plant,
 * where each one may go, and what the reader is told when there is nowhere.
 *
 * Three rules shape all of it.
 *
 *   1. **The destination is asked, never assumed.** An indoor location the
 *      person did not choose is a wrong record that outlives the frost: the
 *      register then says the basil is on the Kitchen Sill, the frost guard
 *      believes it, and next October nobody is warned. A default that is
 *      *remembered* is different from one that is *guessed*, and only the first
 *      is offered here.
 *   2. **A move cannot ride in a batch.** `POST /tending/tasks/complete-batch`
 *      carries `task_ids` and `completed_by` and nothing else, so a relocation
 *      ticked off in a batch would be marked done with the plant still standing
 *      outside — the exact failure this release exists to close. The batch
 *      therefore leaves them alone and says so, rather than quietly succeeding.
 *   3. **Nowhere to put it is a household, not a fault.** A flat with no indoor
 *      location on record is a real flat. The screen says what it cannot offer,
 *      and lets the job be marked done without inventing a move — with the
 *      consequence stated, because a completion that records no destination
 *      leaves the register saying the plant is still outdoors.
 */

import type { SelectOption } from '$ui';
import { taskTypeLabel } from '../shared/labels';
import type { Location, Task } from './api';

/** The two task types the contract's `new_location_id` is about. `cover`
 *  protects a plant where it stands and moves nothing, so it is not here —
 *  `tending.domain.RELOCATION_TASK_TYPES` draws the same line server-side. */
export const RELOCATION_TASK_TYPES = ['bring_indoors', 'return_outdoors'] as const;

export type RelocationType = (typeof RELOCATION_TASK_TYPES)[number];

export function isRelocation(task: Task): boolean {
  return (RELOCATION_TASK_TYPES as readonly string[]).includes(task.task_type);
}

/** Which way the plant is going, or `null` for a task that moves nothing. */
export function direction(task: Task): RelocationType | null {
  return isRelocation(task) ? (task.task_type as RelocationType) : null;
}

/** Where a plant on this task may end up.
 *
 *  A `bring_indoors` task may only end indoors and a `return_outdoors` task
 *  only outdoors — `is_outdoor` is the inventory API's flag on the location and the inventory API's
 *  store keeps the specimen's own copy of it in step on every move, which is
 *  why the screen reads it rather than deciding for itself what counts as
 *  inside. */
export function destinationsFor(task: Task, locations: readonly Location[]): Location[] {
  const going = direction(task);
  if (going === null) return [];
  const wantOutdoor = going === 'return_outdoors';
  return locations.filter((location) => location.is_outdoor === wantOutdoor);
}

/** A location as a line in a picker: its name, then what kind of place it is.
 *
 *  `is_covered` is on the row and is worth showing on a frost night — a covered
 *  porch is shelter and is still outdoors, and the two are easy to confuse at
 *  six in the evening with a torch in the other hand. */
export function locationOptions(locations: readonly Location[]): SelectOption[] {
  return locations.map((location) => ({
    value: location.id,
    plain: `${location.name} — ${locationKind(location)}`,
  }));
}

export function locationKind(location: Location): string {
  const shelter = location.is_covered ? 'covered' : 'open to the sky';
  return location.is_outdoor ? `outdoor ${location.kind}, ${shelter}` : `indoor ${location.kind}`;
}

export function locationName(locations: readonly Location[], id: string): string | null {
  return locations.find((location) => location.id === id)?.name ?? null;
}

// ------------------------------------------------------------ where it came from

/**
 * Where a plant stood before it was carried in, remembered on this device.
 *
 * `return_outdoors` is the reverse trip and should offer the place the plant
 * came from — but nothing in the contract records it. `SpecimenBrief` on a task
 * carries no location; the specimen's own `location` is where it is *now*,
 * which for a plant waiting to go back out is the room it was sheltered in. So
 * the only party that can know is whoever watched the move happen, and on this
 * screen that is the browser it happened in.
 *
 * Kept per-device in `localStorage`, exactly as the design keeps the member
 * picker's default, and treated as a *suggestion* rather than a record: it is
 * checked against the live location list before it is offered, and if the place
 * has gone the screen says it does not know rather than picking another. The
 * honest fix is server-side — a column on the specimen, or `previous_location`
 * on the task — and is escalated to the maintainers and the scheduler rather than papered over here.
 */
export const ORIGIN_STORAGE_KEY = 'moh:came-from';

export type Origins = Record<string, string>;

export function readOrigins(): Origins {
  try {
    const raw = globalThis.localStorage?.getItem(ORIGIN_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Origins = {};
    for (const [specimenId, locationId] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof locationId === 'string' && locationId) out[specimenId] = locationId;
    }
    return out;
  } catch {
    // Private browsing, storage switched off, or something else wrote nonsense
    // under this key. A forgotten origin costs one tap; a screen that will not
    // load because of one is a defect.
    return {};
  }
}

export function writeOrigins(origins: Origins): void {
  try {
    globalThis.localStorage?.setItem(ORIGIN_STORAGE_KEY, JSON.stringify(origins));
  } catch {
    /* see above */
  }
}

/** Record where a plant was standing when it was carried in. Called with the
 *  location it is leaving, before the move, because afterwards it is gone. */
export function rememberOrigin(specimenId: string, locationId: string | null): void {
  if (!locationId) return;
  writeOrigins({ ...readOrigins(), [specimenId]: locationId });
}

/** Forget it once the plant is back out: a stale origin offered next winter is
 *  worse than no suggestion, because it looks like knowledge. */
export function forgetOrigin(specimenId: string): void {
  const origins = readOrigins();
  if (!(specimenId in origins)) return;
  delete origins[specimenId];
  writeOrigins(origins);
}

/**
 * The destination to start the picker on, and whether it is a remembered one.
 *
 * Only ever a place this device watched the plant leave, and only while that
 * place is still a valid destination for this direction. Everything else starts
 * on nothing: an unchosen indoor room is the wrong record that survives the
 * frost, and the reader has to say where it went.
 */
export interface Suggestion {
  locationId: string;
  name: string;
}

export function suggestedDestination(
  task: Task,
  locations: readonly Location[],
  origins: Origins,
): Suggestion | null {
  if (direction(task) !== 'return_outdoors') return null;
  const remembered = origins[task.specimen.id];
  if (!remembered) return null;
  const place = destinationsFor(task, locations).find((location) => location.id === remembered);
  return place ? { locationId: place.id, name: place.name } : null;
}

// ------------------------------------------------------------------ the wording

/** The question the sheet asks, in both halves. */
export function relocationPrompt(task: Task): { themed: string; plain: string } {
  return direction(task) === 'return_outdoors'
    ? {
        themed: 'Where does it go back to?',
        plain: `Say where ${task.specimen.display_name} was put outside`,
      }
    : {
        themed: 'Where has it been taken?',
        plain: `Say where ${task.specimen.display_name} was carried to`,
      };
}

/** Why the sheet exists at all, said once, at the top. */
export const WHY_ASK =
  'The register records where every plant stands, and the frost guard reads it. Marking this ' +
  'done without saying where it went would leave the register — and next winter’s warnings — ' +
  'describing a plant that is no longer there.';

/** There is nowhere of the right kind on record. Not an error: a household. */
export function nowhereToPut(task: Task): string {
  return direction(task) === 'return_outdoors'
    ? 'No outdoor location is on record for this household, so there is nowhere to name as the ' +
        'place it went back to. Add one in the register and this list will fill.'
    : 'No indoor location is on record for this household, so there is nowhere to name as the ' +
        'place it was carried to. A windowsill, a porch, a shed — anywhere the register knows ' +
        'about will do. Add one in the register and this list will fill.';
}

/** What is lost by ticking the job off without naming a destination. Said in
 *  full beside the button that does it, never after the fact. */
export function completingWithoutMoving(task: Task): string {
  const where = direction(task) === 'return_outdoors' ? 'indoors' : 'outdoors';
  return (
    `The job will be recorded as done and the plant will not be moved in the register — it will ` +
    `still be listed ${where}, where it is not. The frost guard reads that listing, so it will ` +
    `go on judging ${task.specimen.display_name} by where the register thinks it is.`
  );
}

/** What the live region says after a plant has actually been moved. Plain
 *  language only: this is read aloud, and the place is the point. */
export function relocationAnnouncement(
  task: Task,
  place: string | null,
  who: string | null,
): string {
  const moved = place
    ? `${task.specimen.display_name} moved to ${place}`
    : `${task.specimen.display_name} marked done — no new location was recorded, so the register is unchanged`;
  return who ? `${moved}, recorded against ${who}.` : `${moved}.`;
}

/** A failed move. The plant did not move and nothing was ticked off — G refuses
 *  the whole request rather than completing half of it, and the sentence says
 *  so, because "it failed" leaves a reader wondering which half. */
export function relocationFailure(problem: string): string {
  return (
    `Nothing was recorded and the plant was not moved. ${problem} ` +
    'The task is still on the round.'
  );
}

// ------------------------------------------------------------------- the batch

/** The relocation tasks in a round, which the batch cannot carry. */
export function unbatchable(due: readonly Task[]): Task[] {
  return due.filter(isRelocation);
}

/** Ids the select-all control may tick: everything a batch can honestly
 *  complete. A relocation left selected would be completed with no destination.
 */
export function batchableIds(due: readonly Task[]): string[] {
  return due.filter((task) => !isRelocation(task)).map((task) => task.id);
}

/** Said on the batch bar whenever the round holds a job it will not tick off.
 *  Names the jobs, so the count on the button and the count on the round can be
 *  reconciled without arithmetic. */
export function batchExclusionNotice(excluded: readonly Task[]): string | null {
  if (!excluded.length) return null;
  const kinds = [...new Set(excluded.map((task) => taskTypeLabel(task.task_type).toLowerCase()))];
  const jobs = excluded.length === 1 ? 'One job' : `${excluded.length} jobs`;
  return (
    `${jobs} on this round move a plant (${kinds.join(', ')}) and are not included above. ` +
    'Each one has to say where the plant went, and the batch has nowhere to carry that — so they ' +
    'are ticked off on their own rows, one at a time.'
  );
}
