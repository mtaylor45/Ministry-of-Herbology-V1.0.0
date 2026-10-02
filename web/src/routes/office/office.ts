/** The Ministry Office's own logic: what an integration's status means in
 *  words, and what a calendar feed may be remembered as.
 *
 *  Two rules here are not negotiable and each has a test:
 *
 *  1. **A feed URL is a password.** `GET /tending/feeds` serves `webcal_url`
 *     and `https_url` on every read (contract 1.7.0). The screen shows a URL
 *     once, from the `POST` that created it, and never again — so every feed
 *     that is *listed* passes through `listedFeed()`, which keeps the name and
 *     the filters and drops both URLs before anything renders or is stored.
 *  2. **`unconfigured` is a setup step, not a fault.** It never takes the
 *     warning tone, and it says what to set.
 */

// ------------------------------------------------------------ integrations

/** `Integration`, contract 1.7.0. `status` is optional until 2.0.0. */
export interface Integration {
  id: string;
  kind: string;
  name: string;
  enabled: boolean;
  status?: 'ok' | 'degraded' | 'down' | 'stale' | 'unconfigured' | string;
  last_ok_at?: string | null;
  last_error?: string | null;
}

export type IntegrationTone = 'ok' | 'warn' | 'setup' | 'off';

export interface IntegrationView {
  /** One or two words, always shown: status is never a colour alone. */
  word: string;
  /** The sentence under it. */
  detail: string;
  tone: IntegrationTone;
  /** The upstream's own error text, shown as given, when there is one. */
  error: string | null;
}

/** What to set for an integration that is not set up yet, per kind. A kind
 *  this build does not know gets the deployment guide, not an invented step. */
export function setupStep(kind: string): string {
  if (kind === 'home_assistant')
    return 'Set MOH_HA_BASE_URL in .env.deploy and create the moh_ha_token secret — the deployment guide, §11.';
  // The hub's `_is_configured`: a named broker *and* an image that carries the MQTT
  // client. The stack names the broker itself, so on a stock deployment the
  // missing half is usually the client library.
  if (kind === 'mqtt')
    return 'Needs MOH_MQTT_HOST (the stack sets it to mosquitto) and an image built with the MQTT client, aiomqtt — the deployment guide, §6 and §7.';
  return 'The operator sets it up in the deployment — see the deployment guide (docs/deploy/).';
}

function when(value: string | null | undefined, now: Date): string | null {
  if (!value) return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  const minutes = Math.round((now.getTime() - at.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  return at.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

/** An integration's status, in words. The server computes `status`; this only says it. A status this build has never heard of is shown as
 *  itself rather than guessed at. */
export function integrationView(row: Integration, now = new Date()): IntegrationView {
  const lastOk = when(row.last_ok_at, now);
  const error = row.last_error?.trim() || null;
  if (!row.enabled)
    return {
      word: 'Switched off',
      detail: 'Turned off in the deployment.',
      tone: 'off',
      error: null,
    };
  switch (row.status) {
    case 'ok':
      return {
        word: 'Answering',
        detail: lastOk ? `Last heard from ${lastOk}.` : 'Answering.',
        tone: 'ok',
        error: null,
      };
    case 'degraded':
      return {
        word: 'Answering, with errors',
        detail: lastOk
          ? `Last answered ${lastOk}, but it has also reported an error since.`
          : 'It answers, but it has also reported an error.',
        tone: 'warn',
        error,
      };
    case 'down':
      return {
        word: 'Not answering',
        detail: lastOk ? `Last answered ${lastOk}.` : 'It has never answered.',
        tone: 'warn',
        error,
      };
    case 'stale':
      return row.last_ok_at
        ? {
            word: 'Gone quiet',
            detail: `No errors, and no news either: last heard from ${lastOk ?? 'some time ago'}.`,
            tone: 'warn',
            error,
          }
        : {
            word: 'Never heard from',
            detail: 'Configured, but it has not answered once yet.',
            tone: 'warn',
            error,
          };
    case 'unconfigured':
      return { word: 'Not set up', detail: setupStep(row.kind), tone: 'setup', error: null };
    case undefined:
      return {
        word: 'Status not reported',
        detail: lastOk ? `The hub did not say; last answered ${lastOk}.` : 'The hub did not say.',
        tone: 'off',
        error,
      };
    default:
      return {
        word: row.status,
        detail: `The hub reported “${row.status}”, which this screen does not know.`,
        tone: 'off',
        error,
      };
  }
}

/** Integrations needing attention first, then set-up steps, then the rest. */
export function sortIntegrations(rows: readonly Integration[], now = new Date()): Integration[] {
  const rank: Record<IntegrationTone, number> = { warn: 0, setup: 1, ok: 2, off: 3 };
  return [...rows].sort(
    (a, b) =>
      rank[integrationView(a, now).tone] - rank[integrationView(b, now).tone] ||
      a.name.localeCompare(b.name),
  );
}

// ------------------------------------------------------------------- feeds

export type TaskType =
  | 'water'
  | 'fertilize'
  | 'mist'
  | 'prune'
  | 'repot'
  | 'inspect'
  | 'bring_indoors'
  | 'return_outdoors'
  | 'cover'
  | 'rotate';

export interface CalendarFilters {
  outdoor?: boolean | null;
  task_types?: TaskType[];
  location_ids?: string[];
}

/** `CalendarFeed` as the API sends it — URLs and all. Never rendered, never
 *  kept: see `listedFeed()` and `createdFeed()`. */
export interface CalendarFeedResponse {
  id: string;
  member_id?: string;
  name: string;
  webcal_url: string;
  https_url?: string;
  filters?: CalendarFilters;
  push_target?: string;
  last_rendered_at?: string | null;
  revoked?: boolean;
}

/** A feed as the list shows it. **No URL field exists on this type**, so a
 *  list row cannot render one by mistake. */
export interface ListedFeed {
  id: string;
  name: string;
  member_id: string | null;
  filters: CalendarFilters;
  last_rendered_at: string | null;
  revoked: boolean;
}

/** Strip a feed down to what may be listed. Built field by field rather than
 *  by deleting the URLs, so a URL field the API adds later is left out too. */
export function listedFeed(feed: CalendarFeedResponse): ListedFeed {
  return {
    id: feed.id,
    name: feed.name,
    member_id: feed.member_id ?? null,
    filters: {
      outdoor: feed.filters?.outdoor ?? null,
      task_types: [...(feed.filters?.task_types ?? [])],
      location_ids: [...(feed.filters?.location_ids ?? [])],
    },
    last_rendered_at: feed.last_rendered_at ?? null,
    revoked: Boolean(feed.revoked),
  };
}

/** The one moment a URL is shown: what the creating `POST` returned. */
export interface CreatedFeed {
  id: string;
  name: string;
  webcal_url: string;
  https_url: string | null;
}

export function createdFeed(feed: CalendarFeedResponse): CreatedFeed {
  return {
    id: feed.id,
    name: feed.name,
    webcal_url: feed.webcal_url,
    https_url: feed.https_url || null,
  };
}

/** The feeds, revoked ones last, then by name. */
export function sortFeeds(feeds: readonly ListedFeed[]): ListedFeed[] {
  return [...feeds].sort(
    (a, b) => Number(a.revoked) - Number(b.revoked) || a.name.localeCompare(b.name),
  );
}

export const TASK_TYPE_WORDS: Record<TaskType, string> = {
  water: 'Water',
  fertilize: 'Fertilize',
  mist: 'Mist',
  prune: 'Prune',
  repot: 'Repot',
  inspect: 'Inspect for pests',
  bring_indoors: 'Bring indoors',
  return_outdoors: 'Put back outside',
  cover: 'Cover against frost',
  rotate: 'Rotate',
};

/** What a feed carries, in words, for its list row. */
export function filterSummary(
  filters: CalendarFilters,
  locationName: (id: string) => string | undefined = () => undefined,
): string {
  const parts: string[] = [];
  if (filters.outdoor === true) parts.push('outdoor plants');
  else if (filters.outdoor === false) parts.push('indoor plants');
  else parts.push('every plant');
  const types = filters.task_types ?? [];
  parts.push(
    types.length ? types.map((t) => TASK_TYPE_WORDS[t] ?? t).join(', ') : 'every kind of task',
  );
  const ids = filters.location_ids ?? [];
  if (ids.length) {
    const names = ids.map((id) => locationName(id) ?? 'a location no longer listed');
    parts.push(`at ${names.join(', ')}`);
  }
  return parts.join(' · ');
}

/** What `POST /tending/feeds` is sent. Empty filters are left out: a feed with
 *  no filters carries everything. */
export function feedBody(input: {
  name: string;
  memberId: string;
  outdoor: '' | 'true' | 'false';
  taskTypes: readonly TaskType[];
}): { member_id: string; name: string; filters: CalendarFilters } {
  const filters: CalendarFilters = {};
  if (input.outdoor) filters.outdoor = input.outdoor === 'true';
  if (input.taskTypes.length) filters.task_types = [...input.taskTypes];
  return { member_id: input.memberId, name: input.name.trim(), filters };
}

// --------------------------------------------------------------- household

export const ROLE_WORDS: Record<string, string> = {
  keeper: 'Keeper',
  tender: 'Tender',
  observer: 'Observer',
};
