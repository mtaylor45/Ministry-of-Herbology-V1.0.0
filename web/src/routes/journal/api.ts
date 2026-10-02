/** What the journal reads and writes, typed against the frozen contract.
 *
 * `contracts/openapi/openapi.yaml` is the authority: where it and this file
 * disagree, this file is the bug. The journal owns this directory; the
 * transport half comes from `../shared/http.ts`, which belongs to the app's screens and is
 * imported rather than copied.
 *
 * Three shapes below are **not** in the contract as frozen, and each is marked:
 *
 *   - `POST /journal/plates/{id}/approve` — the contract declares `approved`
 *     and the schema puts `approved_by` behind it, but nothing approves a
 *     plate. Escalated in the pull request.
 *   - `member_id` on a new field note — the design picks the member at write
 *     time and the frozen body has no field for them.
 *   - `?variant=thumb` on a plate's image — `Plate.image_url` is an
 *     unconstrained string and the bytes have to come from somewhere.
 *
 * The *reason* a plant has no plate now has a home: `GET /journal/coverage`,
 * declared in 1.6.0 shipped a book that could name a
 * blank leaf but not explain it. `reason_kind` is a closed set, so the screen
 * branches on it rather than printing prose it cannot check; `reason` is the
 * pipeline's own sentence and is shown as written.
 *
 * Coverage is an *extra* read, not a required one. If it fails, the book still
 * pages through every plant and still says which have no plate — it just falls
 * back to the generic sentence. A blank leaf with no explanation is worse than
 * one with it and far better than no book.
 */

import { get, post, type Fetcher } from '../shared/http';

export { ApiError, reason, settle, type Fetched, type Fetcher } from '../shared/http';

/** `Plate.origin`. Three values, and the first two mean very different things
 *  to a reader: one was collected, one was drawn to order. */
export type PlateOrigin = 'public_domain' | 'generated' | 'user_upload';

/** `Plate`, exactly as the contract declares it. */
export interface Plate {
  id: string;
  species_id: string | null;
  specimen_id: string | null;
  image_url: string;
  thumb_url: string | null;
  origin: PlateOrigin;
  /** Null for a generated plate, always. Never filled in client-side. */
  license: string | null;
  /** Null for a generated plate, always. */
  attribution: string | null;
  approved: boolean;
}

export interface Member {
  id: string;
  name: string;
  role: string;
  notify_prefs?: Record<string, unknown>;
}

/** `FieldNote`. `written_by` is a bare `$ref` in the contract, so the API omits
 *  it rather than serving null when nobody is recorded — hence `?`, not
 *  `| null`. A note with no author is a note with no author. */
export interface FieldNote {
  id: string;
  body: string;
  written_at: string;
  written_by?: Member;
}

/** The subset of the contract's `Specimen` this screen needs.
 *
 *  Named `JournalSpecimen` rather than `SpecimenBrief` on purpose: the contract
 *  has a `SpecimenBrief` and it is a *different, smaller* shape with no
 *  species on it. `GET /specimens` serves full `Specimen` objects, and the
 *  species is what joins a plant to its plate.
 */
export interface JournalSpecimen {
  id: string;
  display_name: string;
  species?: { id: string; accepted_name?: string | null } | null;
  primary_photo_url?: string | null;
}

interface SpecimenPage {
  items: JournalSpecimen[];
  total: number;
}

/** `PlateCoverageEntry.reason_kind` — a closed set, so a screen may branch on
 *  it exhaustively. A kind this client does not know about falls back to the
 *  generic sentence rather than rendering `undefined`. */
export type ReasonKind =
  | 'no_candidate'
  | 'unlicensed_candidate'
  | 'generation_unavailable'
  | 'unusable_image'
  | 'store_unavailable'
  | 'not_run';

export interface PlateCoverageEntry {
  specimen: { id: string; display_name: string; is_outdoor?: boolean; thumb_url?: string | null };
  state: 'approved' | 'waiting' | 'absent';
  plate_id: string | null;
  reason_kind: ReasonKind | null;
  /** The pipeline's own sentence. Prose, not contract — branch on `reason_kind`. */
  reason: string | null;
}

export interface PlateCoverage {
  total: number;
  approved: number;
  waiting: number;
  absent: number;
  generated: number;
  specimens: PlateCoverageEntry[];
}

export const reads = {
  plates: (fetcher: Fetcher, approved?: boolean): Promise<Plate[]> =>
    get<Plate[]>(
      approved === undefined ? '/journal/plates' : `/journal/plates?approved=${approved}`,
      fetcher,
    ),

  notes: (specimenId: string, fetcher: Fetcher): Promise<FieldNote[]> =>
    get<FieldNote[]>(`/journal/${specimenId}/notes`, fetcher),

  /** Every specimen, so the book can say which plants it has no page for.
   *  The inventory API's endpoint; read-only here. */
  specimens: (fetcher: Fetcher): Promise<SpecimenPage> =>
    get<SpecimenPage>('/specimens?limit=200', fetcher),

  specimen: (specimenId: string, fetcher: Fetcher): Promise<JournalSpecimen> =>
    get<JournalSpecimen>(`/specimens/${specimenId}`, fetcher),

  members: (fetcher: Fetcher): Promise<Member[]> => get<Member[]>('/members', fetcher),

  /** Why each leaf is blank, and the five counts. */
  coverage: (fetcher: Fetcher): Promise<PlateCoverage> =>
    get<PlateCoverage>('/journal/coverage', fetcher),
};

export const writes = {
  /** Write an observation down.
   *
   *  `memberId` is additive (see the module docstring). Omitted, the note is
   *  stored without an author rather than with a guessed one.
   */
  note: (
    specimenId: string,
    body: string,
    fetcher: Fetcher,
    memberId?: string,
  ): Promise<FieldNote> =>
    post<FieldNote>(
      `/journal/${specimenId}/notes`,
      memberId ? { body, member_id: memberId } : { body },
      fetcher,
    ),

  /** The maintainers named member accepts a plate. **Not in the frozen contract.**
   *
   *  `memberId` is required by the route and by this function: an approval
   *  with no approver is the one state the field exists to rule out, so there
   *  is no overload that omits it.
   */
  approve: (plateId: string, memberId: string, fetcher: Fetcher): Promise<Plate> =>
    post<Plate>(`/journal/plates/${plateId}/approve`, { member_id: memberId }, fetcher),
};
