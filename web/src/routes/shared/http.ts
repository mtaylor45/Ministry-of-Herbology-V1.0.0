/** The reads every screen in this parts of the project makes, and how they fail.
 *
 * `$api/client.ts` belongs to the design system and carries the shapes Morning
 * Rounds needs; the rest of the app's screens' screens type their own calls. This
 * module is the transport half of that — the part the Specimen facets and the
 * Almanac would otherwise each own a copy of, including the sentences a reader
 * sees when a panel cannot be filled. Two copies of those sentences is two
 * places for them to drift apart, and the drift shows up on screen.
 *
 * The shapes themselves stay with the screens that read them: this file knows
 * about HTTP, not about plants or weather.
 */

export const BASE = '/api/v1';

export type Fetcher = typeof fetch;

export class ApiError extends Error {
  constructor(
    readonly path: string,
    readonly status: number,
    readonly statusText: string,
  ) {
    super(`${status} ${statusText} for ${path}`);
    this.name = 'ApiError';
  }
}

export async function get<T>(path: string, fetcher: Fetcher): Promise<T> {
  const response = await fetcher(`${BASE}${path}`, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
  return (await response.json()) as T;
}

/** A write, with the same failure vocabulary as a read.
 *
 *  Morning Rounds is the first screen in this parts of the project that writes anything,
 *  and a completion that silently fails is worse than one that refuses: the
 *  reader walks away believing the plant is watered. Every caller therefore
 *  gets an `ApiError` it has to deal with, never a quietly discarded response.
 */
export async function post<T>(path: string, body: unknown, fetcher: Fetcher): Promise<T> {
  const response = await fetcher(`${BASE}${path}`, {
    method: 'POST',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(path, response.status, response.statusText);
  return (await response.json()) as T;
}

/** A panel's data, or the plain reason it is missing. Never both, never neither.
 *
 *  A screen asks several endpoints for its panels. One of them failing must
 *  cost the reader that panel and nothing else — a blank Tending page because
 *  the frost lookahead timed out is worse than a page that says so. */
export type Fetched<T> = { value: T; error: null } | { value: null; error: string };

/** Run a read and keep its failure as a sentence rather than as an exception. */
export async function settle<T>(work: Promise<T>): Promise<Fetched<T>> {
  try {
    return { value: await work, error: null };
  } catch (cause) {
    return { value: null, error: reason(cause) };
  }
}

/** What went wrong, in words a person reads outdoors rather than a stack trace. */
export function reason(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 404) return 'The greenhouse has no record of this yet.';
    if (cause.status === 405 || cause.status === 501)
      return 'The API does not answer this yet — the screen is ready, the endpoint is not.';
    if (cause.status === 422)
      return 'The greenhouse would not accept that — something in the request was not valid.';
    if (cause.status >= 500) return `The greenhouse answered with an error (${cause.status}).`;
    return `The greenhouse refused the request (${cause.status}).`;
  }
  if (cause instanceof Error) return cause.message;
  return 'Something went wrong, and it did not say what.';
}
