/** Is the greenhouse reachable, and is what is on screen the saved copy?
 *
 * A store the shell reads to decide whether to show the offline notice. It is
 * fed by two things: the browser's own `online`/`offline` events, and messages
 * from the service worker saying a response came from the cache
 * (`moh:from-cache`, `moh:page-from-cache`) or fresh from the network
 * (`moh:fresh`). The reducer is a plain function so `connectivity.test.ts` can
 * drive it without a browser.
 */

import { writable, type Readable } from 'svelte/store';

export interface FromCache {
  /** ISO timestamp the copy was stored, or null if the copy did not say. */
  cachedAt: string | null;
  /** Whether it was the page itself or one of the reads it made. */
  what: 'page' | 'data';
}

export interface Connectivity {
  online: boolean;
  fromCache: FromCache | null;
}

export type ConnectivityEvent =
  | { type: 'online' }
  | { type: 'offline' }
  | { type: 'moh:from-cache'; cachedAt?: string | null }
  | { type: 'moh:page-from-cache'; cachedAt?: string | null }
  | { type: 'moh:fresh' }
  | { type: 'navigated' };

export const INITIAL: Connectivity = { online: true, fromCache: null };

/** Fold one event into the state. */
export function reduce(state: Connectivity, event: ConnectivityEvent): Connectivity {
  switch (event.type) {
    case 'online':
      return { ...state, online: true };
    case 'offline':
      return { ...state, online: false };
    case 'moh:page-from-cache':
      return { ...state, fromCache: { cachedAt: event.cachedAt ?? null, what: 'page' } };
    case 'moh:from-cache':
      // A page served from the copy already says so; a read within it does not
      // make it more so, and the page's own time is the one to show.
      if (state.fromCache?.what === 'page') return state;
      return { ...state, fromCache: { cachedAt: event.cachedAt ?? null, what: 'data' } };
    case 'moh:fresh':
      // One fresh read does not un-cache a page that came from the copy.
      return state.fromCache?.what === 'data' ? { ...state, fromCache: null } : state;
    case 'navigated':
      // A new page starts honest: if it too comes from the copy, the worker
      // says so again.
      return { ...state, fromCache: null };
    default:
      return state;
  }
}

/** Whether the notice shows at all. */
export function shouldNotice(state: Connectivity): boolean {
  return !state.online || state.fromCache !== null;
}

/** What the notice says. Plain language; the themed line is the component's. */
export function sentence(state: Connectivity, formatAsOf: (iso: string) => string): string {
  const saved = state.fromCache?.cachedAt
    ? `the copy saved ${formatAsOf(state.fromCache.cachedAt)}`
    : 'a copy saved on this device';
  if (!state.online && state.fromCache) {
    return `You are offline. This is ${saved}. Nothing you mark here is sent until the signal returns.`;
  }
  if (!state.online) {
    return 'You are offline. Pages you opened recently are still here; anything else needs a signal.';
  }
  return `The greenhouse did not answer, so this is ${saved}.`;
}

let state: Connectivity = INITIAL;
const store = writable<Connectivity>(state);

/** The live state. On the server it is the initial state and nothing more. */
export const connectivity: Readable<Connectivity> = { subscribe: store.subscribe };

/** Fold an event into the live state. The shell calls this on navigation;
 *  `startConnectivity` calls it for everything the browser and worker say. */
export function dispatch(event: ConnectivityEvent): void {
  state = reduce(state, event);
  store.set(state);
}

/** Listen to the browser and the worker. Returns the function that stops. */
export function startConnectivity(): () => void {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return () => {};
  dispatch({ type: navigator.onLine ? 'online' : 'offline' });

  const onOnline = () => dispatch({ type: 'online' });
  const onOffline = () => dispatch({ type: 'offline' });
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);

  const worker = navigator.serviceWorker;
  const onMessage = (message: MessageEvent) => {
    const data = message.data as ConnectivityEvent | null;
    if (data && typeof data.type === 'string' && data.type.startsWith('moh:')) dispatch(data);
  };
  worker?.addEventListener('message', onMessage);
  // The worker chose this page's response before the page existed; ask it.
  void worker?.ready.then((registration) =>
    registration.active?.postMessage({ type: 'moh:hello' }),
  );

  return () => {
    window.removeEventListener('online', onOnline);
    window.removeEventListener('offline', onOffline);
    worker?.removeEventListener('message', onMessage);
  };
}
