/** Every plant the sheet could hold, not only the ones already on it.
 *
 * The releases's exit criterion is that **every specimen can be pinned**, and in
 * a live deployment the map alone cannot get you there. `GET /grounds/pins`
 * answers for pins: in mock mode the maps module's writable repository synthesises one for
 * every fixture plant, but the database repository selects
 * `WHERE map_layer_id IS NOT NULL AND pin_px IS NOT NULL` — so on a real
 * deployment, where nothing is pinned yet, it answers `[]`. The map then draws
 * an empty sheet with an empty list beside it, and there is no control anywhere
 * on the screen for placing a first pin. The same hole swallows one plant at a
 * time afterwards, because lifting a pin deletes the row rather than nulling
 * it: a plant taken off the map cannot be put back.
 *
 * The fix belongs to the route, because it is a composition of two endpoints
 * and not a change to either: the Register says which plants exist, the Grounds
 * says which are placed, and a plant in the first and not the second is a row
 * the list should carry. `Pin.px` is already contracted as nullable and
 * `web/src/lib/map/types.ts` already defines a null one as *"the specimen is in
 * the Register but not yet placed"*, which is exactly what these rows say. The maps module's
 * `PinList` renders them as unplaced and offers "Place"; `pinRows` counts only
 * the placed ones, so nothing in the numbering shifts.
 *
 * Nothing is invented here. Every row is a plant the Register returned, and the
 * only field this module supplies is the sheet it could go on.
 */

import type { Pin } from '$map';
import { get, type Fetcher } from '../shared/http';

/** What the roster needs off a Register entry. The contract's `Specimen`, in part. */
export interface RegisterEntry {
  id: string;
  display_name: string;
  is_outdoor: boolean;
  status: string;
  primary_photo_url?: string | null;
}

interface SpecimenPage {
  items: RegisterEntry[];
  next_cursor?: string | null;
  total?: number;
}

/** Statuses that mean the plant is no longer there to be looked at.
 *
 *  the design — a plant set aside is still named, so these keep their Register
 *  entry and their pin if they have one. They are simply not offered as
 *  somewhere to put a *new* pin: a map of the grounds is a map of what is on
 *  them. */
export const NOT_IN_KEEPING = new Set(['lost', 'given_away', 'archived']);

/** `GET /specimens` is a cursor page, and this screen wants the whole roster.
 *
 *  Bounded rather than trusting, because an endpoint that keeps handing back a
 *  cursor must not become an infinite loop on a phone. The cap is far above a
 *  household and the caller is told when it bites. */
export const ROSTER_PAGE_LIMIT = 200;
export const ROSTER_MAX_PAGES = 10;

export interface Roster {
  entries: RegisterEntry[];
  /** True when the cap stopped the walk, so the roster is incomplete. */
  truncated: boolean;
}

export async function readRoster(fetcher: Fetcher): Promise<Roster> {
  const entries: RegisterEntry[] = [];
  let cursor: string | null = null;

  for (let pages = 0; pages < ROSTER_MAX_PAGES; pages += 1) {
    const query = new URLSearchParams({ limit: String(ROSTER_PAGE_LIMIT) });
    if (cursor) query.set('cursor', cursor);
    const page: SpecimenPage = await get<SpecimenPage>(`/specimens?${query.toString()}`, fetcher);
    entries.push(...(page.items ?? []));
    cursor = page.next_cursor ?? null;
    if (!cursor) return { entries, truncated: false };
  }
  return { entries, truncated: true };
}

/** The pins, plus a placeable row on every sheet for every unpinned plant.
 *
 * `register` being `null` means the Register could not be read — in which case
 * this hands back the pins untouched rather than guessing that there are no
 * other plants.
 */
export function placeable(
  layers: readonly { id: string }[],
  pins: readonly Pin[],
  register: readonly RegisterEntry[] | null,
): Pin[] {
  if (!register) return [...pins];
  const known = new Set(pins.map((pin) => pin.specimen_id));
  const rows: Pin[] = [...pins];

  for (const entry of register) {
    if (known.has(entry.id) || NOT_IN_KEEPING.has(entry.status)) continue;
    for (const layer of layers) {
      rows.push({
        specimen_id: entry.id,
        layer_id: layer.id,
        px: null,
        specimen: {
          id: entry.id,
          display_name: entry.display_name,
          is_outdoor: entry.is_outdoor,
          thumb_url: entry.primary_photo_url ?? null,
        },
      });
    }
  }
  return rows;
}

/** How many plants in the Register no sheet holds a pin for. */
export function unpinnedCount(
  pins: readonly Pin[],
  register: readonly RegisterEntry[] | null,
): number {
  if (!register) return 0;
  const placed = new Set(pins.filter((pin) => pin.px !== null).map((pin) => pin.specimen_id));
  return register.filter((entry) => !placed.has(entry.id) && !NOT_IN_KEEPING.has(entry.status))
    .length;
}
