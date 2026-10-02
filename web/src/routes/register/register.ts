/** The Register's own logic: what a filter is, how it becomes a URL, and what a
 *  row says about a plant that the API does not put into words.
 *
 *  A filter is a URL (`/register?q=basil&status=dormant`) so a person can
 *  bookmark one and the back button undoes one. That makes the URL the single
 *  source of truth: the page reads its filters from `url.searchParams`, the
 *  form writes them back by navigating, and nothing in between keeps a second
 *  copy that could disagree with the address bar.
 *
 *  Every value here is the contract's (`listSpecimens`, contract 1.7.0). Where
 *  the contract has no word for something — the Register's groups, a row's
 *  toxicity — the comment beside it says so rather than inventing one.
 */

import type { SpecimenStatus } from '../specimen/[id]/api';

// ------------------------------------------------------------------ shapes

/** `TaskBrief`. Nullable on `Specimen.next_task`: nothing scheduled is normal. */
export interface TaskBrief {
  id?: string;
  task_type?: string;
  due_at?: string;
  status?: string;
  plain_title?: string;
}

export interface RegisterLocation {
  id: string;
  name: string;
  kind: 'area' | 'zone' | 'bed' | 'room' | 'shelf' | string;
  is_outdoor: boolean;
  parent_id?: string | null;
  sun_exposure?: string | null;
  specimen_count?: number;
}

/** `Specimen`, the fields a Register row reads. */
export interface RegisterSpecimen {
  id: string;
  display_name: string;
  nickname?: string | null;
  cultivar?: string | null;
  species?: {
    id?: string;
    accepted_name?: string;
    common_name?: string | null;
  } | null;
  is_group?: boolean;
  count?: number;
  location?: RegisterLocation | null;
  is_outdoor: boolean;
  status: SpecimenStatus | string;
  primary_photo_url?: string | null;
  next_task?: TaskBrief | null;
}

export interface SpecimenPage {
  items: RegisterSpecimen[];
  next_cursor?: string | null;
  total?: number;
}

/** The two toxicity flags from `Species`. `null` is "nobody has checked", which
 *  is not "safe" and is never drawn as safe. */
export interface SpeciesToxicity {
  id: string;
  toxic_to_pets: boolean | null;
  toxic_to_children: boolean | null;
}

// ----------------------------------------------------------------- filters

export const STATUSES: SpecimenStatus[] = [
  'thriving',
  'struggling',
  'dormant',
  'overwintering',
  'lost',
  'given_away',
  'archived',
];

export interface RegisterFilters {
  q: string;
  location_id: string;
  /** `''` any, `'true'` outdoors, `'false'` indoors — as the query string has it. */
  outdoor: '' | 'true' | 'false';
  status: '' | SpecimenStatus;
  toxic_to_pets: '' | 'true' | 'false';
}

export const NO_FILTERS: RegisterFilters = {
  q: '',
  location_id: '',
  outdoor: '',
  status: '',
  toxic_to_pets: '',
};

/** The page size. The contract's default is 50; a Register row carries a
 *  photograph, so a phone gets a shorter first page and "Show more". */
export const PAGE_SIZE = 25;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function flag(value: string | null): '' | 'true' | 'false' {
  return value === 'true' || value === 'false' ? value : '';
}

/** Read the filters out of an address. Anything the contract would refuse — a
 *  status it has no word for, a location that is not a uuid — is dropped here
 *  rather than sent, so a mistyped bookmark shows the whole Register instead of
 *  a 422. */
export function parseFilters(params: URLSearchParams): RegisterFilters {
  const status = params.get('status') ?? '';
  const location = params.get('location_id') ?? '';
  return {
    q: (params.get('q') ?? '').trim(),
    location_id: UUID.test(location) ? location : '',
    outdoor: flag(params.get('outdoor')),
    status: (STATUSES as string[]).includes(status) ? (status as SpecimenStatus) : '',
    toxic_to_pets: flag(params.get('toxic_to_pets')),
  };
}

/** The filters that are set, in a fixed order, with the empty ones left out —
 *  so two people who chose the same filters bookmark the same address. */
export function filterParams(filters: RegisterFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of Object.keys(NO_FILTERS) as (keyof RegisterFilters)[]) {
    const value = filters[key].trim();
    if (value) params.set(key, value);
  }
  return params;
}

/** The Register's address for these filters. */
export function registerHref(filters: RegisterFilters): string {
  const query = filterParams(filters).toString();
  return query ? `/register?${query}` : '/register';
}

/** The API path for one page of these filters. */
export function specimensPath(filters: RegisterFilters, cursor?: string | null): string {
  const params = filterParams(filters);
  params.set('limit', String(PAGE_SIZE));
  if (cursor) params.set('cursor', cursor);
  return `/specimens?${params.toString()}`;
}

export function hasFilters(filters: RegisterFilters): boolean {
  return filterParams(filters).toString() !== '';
}

// ------------------------------------------------------------ the words

export const STATUS_WORDS: Record<SpecimenStatus, string> = {
  thriving: 'Thriving',
  struggling: 'Struggling',
  dormant: 'Dormant',
  overwintering: 'Overwintering',
  lost: 'Lost',
  given_away: 'Given away',
  archived: 'Archived',
};

export const KIND_WORDS: Record<string, string> = {
  area: 'area',
  zone: 'zone',
  bed: 'bed',
  room: 'room',
  shelf: 'shelf',
};

/** A location as the filter offers it: its name, then what kind of place and
 *  whether it is outside — so the two beds are told apart from the two rooms
 *  without a colour or an icon. */
export function locationOption(location: RegisterLocation): string {
  const kind = KIND_WORDS[location.kind] ?? location.kind;
  return `${location.name} — ${kind}, ${location.is_outdoor ? 'outdoors' : 'indoors'}`;
}

/** Locations in the order the filter lists them: indoors first, then by name. */
export function sortLocations(locations: readonly RegisterLocation[]): RegisterLocation[] {
  return [...locations].sort(
    (a, b) => Number(a.is_outdoor) - Number(b.is_outdoor) || a.name.localeCompare(b.name),
  );
}

/** The species line: common name, then the accepted name, then the cultivar.
 *  A plant whose species is not yet resolved says so rather than going blank. */
export function speciesLine(specimen: RegisterSpecimen): string {
  const species = specimen.species;
  const cultivar = specimen.cultivar ? ` ‘${specimen.cultivar}’` : '';
  if (!species?.accepted_name) return `Species not yet identified${cultivar}`;
  const common = species.common_name?.trim();
  const accepted = `${species.accepted_name}${cultivar}`;
  return common && common.toLowerCase() !== specimen.display_name.toLowerCase()
    ? `${common} · ${accepted}`
    : accepted;
}

/** Where the plant stands, and whether that is in or out. */
export function placeLine(specimen: RegisterSpecimen): string {
  const where = specimen.is_outdoor ? 'outdoors' : 'indoors';
  if (!specimen.location) return `No location recorded · ${where}`;
  const kind = KIND_WORDS[specimen.location.kind];
  return `${specimen.location.name}${kind ? ` (${kind})` : ''} · ${where}`;
}

/** A group is one Register entry standing for several plants (`is_group`,
 *  `count`). The contract has no other grouping — see the PR. */
export function groupLine(specimen: RegisterSpecimen): string | null {
  if (!specimen.is_group) return null;
  const count = specimen.count ?? 0;
  return count > 1 ? `A group of ${count} plants` : 'A group';
}

export interface ToxicityMark {
  /** Words, always: the mark is never a colour alone. */
  text: string;
  /** Whether this is a warning. Shown with the warning icon *and* the words. */
  warn: boolean;
}

/** What a row says about toxicity.
 *
 *  `Specimen` does not carry toxicity; `Species` does. The Register reads the
 *  species list once and looks each row up. `null` on the species, a species
 *  that is not in the list, or no species at all is "not checked" — never
 *  "safe". If the list itself could not be read, the row says that instead,
 *  because a missing warning would read as an all-clear. */
export function toxicityMark(
  specimen: RegisterSpecimen,
  species: ReadonlyMap<string, SpeciesToxicity> | null,
): ToxicityMark {
  if (species === null) return { text: 'Toxicity could not be read', warn: false };
  const known = specimen.species?.id ? species.get(specimen.species.id) : undefined;
  const pets = known?.toxic_to_pets ?? null;
  const children = known?.toxic_to_children ?? null;
  if (pets && children) return { text: 'Toxic to pets and children', warn: true };
  if (pets) return { text: 'Toxic to pets', warn: true };
  if (children) return { text: 'Toxic to children', warn: true };
  if (pets === false && children === false) return { text: 'Not known to be toxic', warn: false };
  return { text: 'Toxicity not checked', warn: false };
}

export function speciesIndex(rows: readonly SpeciesToxicity[]): Map<string, SpeciesToxicity> {
  return new Map(rows.map((row) => [row.id, row]));
}

/** The next job, if the API sent one. `next_task` is null on every fixture
 *  plant today; the line is built for the day it is not. */
export function nextTaskLine(task: TaskBrief | null | undefined, now = new Date()): string | null {
  if (!task) return null;
  const what = task.plain_title?.trim() || task.task_type || 'A task';
  if (!task.due_at) return `Next: ${what}`;
  const due = new Date(task.due_at);
  if (Number.isNaN(due.getTime())) return `Next: ${what}`;
  const days = Math.round(
    (Date.UTC(due.getFullYear(), due.getMonth(), due.getDate()) -
      Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) /
      86_400_000,
  );
  const when =
    days < 0
      ? 'overdue'
      : days === 0
        ? 'due today'
        : days === 1
          ? 'due tomorrow'
          : `due ${due.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}`;
  return `Next: ${what}, ${when}`;
}

/** The sentence above the list: how many, and which filters made it so. */
export function summarySentence(
  shown: number,
  total: number | undefined,
  filters: RegisterFilters,
  locations: readonly RegisterLocation[],
): string {
  const count = total ?? shown;
  const noun = count === 1 ? 'entry' : 'entries';
  const described = describeFilters(filters, locations);
  const base = described.length
    ? `${count} ${noun} ${described.join(', ')}.`
    : `${count} ${noun} in the Register.`;
  return shown < count ? `${base} Showing the first ${shown}.` : base;
}

/** Each active filter, in words — what the summary and an empty result say. */
export function describeFilters(
  filters: RegisterFilters,
  locations: readonly RegisterLocation[],
): string[] {
  const parts: string[] = [];
  if (filters.q) parts.push(`matching “${filters.q}”`);
  if (filters.location_id) {
    const found = locations.find((l) => l.id === filters.location_id);
    parts.push(`at ${found ? found.name : 'the chosen location'}`);
  }
  if (filters.outdoor === 'true') parts.push('outdoors');
  if (filters.outdoor === 'false') parts.push('indoors');
  if (filters.status) parts.push(`with status “${STATUS_WORDS[filters.status]}”`);
  if (filters.toxic_to_pets === 'true') parts.push('toxic to pets');
  if (filters.toxic_to_pets === 'false') parts.push('not marked toxic to pets');
  return parts;
}

/** What an empty list means, and what to do about it. An empty household and
 *  a filter that matches nothing are different problems, and the second names
 *  the filter so the reader knows which one to loosen. */
export function emptySentence(
  filters: RegisterFilters,
  locations: readonly RegisterLocation[],
): { plain: string; body: string } {
  if (!hasFilters(filters)) {
    return {
      plain: 'No plants in the Register yet',
      body: 'Add the first one with “Add a plant” below: type its name, and the Ministry looks up the species and its care.',
    };
  }
  const described = describeFilters(filters, locations);
  return {
    plain: 'Nothing matches these filters',
    body: `No entry ${described.join(', ')}. Clear a filter to widen the search.`,
  };
}
