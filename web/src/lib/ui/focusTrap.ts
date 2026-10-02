/** Focus trapping for dialogs and sheets.
 *
 * The decision of *what to focus next* is a pure function over a list of
 * candidates, so it can be tested without a browser; the Svelte action is a
 * thin wrapper that wires it to real key events and restores focus on the way
 * out. A dialog that traps focus but forgets to give it back is worse than one
 * that never trapped it.
 */

export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/** The shape `resolveTrapTarget` needs. Real elements satisfy it; so do stubs. */
export interface FocusCandidate {
  hidden?: boolean;
  getAttribute?(name: string): string | null;
  focus?(): void;
}

/** Drop candidates that are present in the DOM but cannot actually take focus. */
export function focusable<T extends FocusCandidate>(candidates: readonly T[]): T[] {
  return candidates.filter((el) => {
    if (el.hidden) return false;
    const ariaHidden = el.getAttribute?.('aria-hidden');
    if (ariaHidden === 'true') return false;
    const inert = el.getAttribute?.('inert');
    return inert === null || inert === undefined;
  });
}

export interface TrapKey {
  key: string;
  shiftKey?: boolean;
}

/**
 * Where focus should go for a keypress inside a trap.
 *
 * Returns the element to focus, or `null` when the key is none of our business.
 * Tab from the last element wraps to the first; Shift+Tab from the first wraps
 * to the last; a Tab from somewhere outside the list lands on the first.
 */
export function resolveTrapTarget<T extends FocusCandidate>(
  event: TrapKey,
  candidates: readonly T[],
  active: T | null | undefined,
): T | null {
  if (event.key !== 'Tab') return null;
  const items = focusable(candidates);
  if (items.length === 0) return null;

  const back = Boolean(event.shiftKey);
  const index = active ? items.indexOf(active) : -1;
  if (index === -1) return back ? items[items.length - 1] : items[0];

  const last = items.length - 1;
  if (!back && index === last) return items[0];
  if (back && index === 0) return items[last];
  return null; // the browser's own Tab does the right thing in the middle
}

export interface FocusTrapOptions {
  /** Called when Escape is pressed, if the dialog is dismissible. */
  onescape?: () => void;
  /** Focus this when the trap opens; defaults to the first focusable child. */
  initial?: () => HTMLElement | null | undefined;
}

/**
 * Svelte action: `<div use:focusTrap={{ onescape }}>`.
 *
 * Remembers what had focus, moves focus inside, keeps Tab within the node, and
 * puts focus back where it was when the node goes away.
 */
export function focusTrap(node: HTMLElement, options: FocusTrapOptions = {}) {
  let settings = options;
  const previous = typeof document !== 'undefined' ? document.activeElement : null;

  const items = () => focusable(Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)));

  const onkeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      settings.onescape?.();
      return;
    }
    const target = resolveTrapTarget(event, items(), document.activeElement as HTMLElement | null);
    if (target) {
      event.preventDefault();
      target.focus?.();
    }
  };

  const first = settings.initial?.() ?? items()[0] ?? node;
  first.focus?.();
  node.addEventListener('keydown', onkeydown);

  return {
    update(next: FocusTrapOptions) {
      settings = next ?? {};
    },
    destroy() {
      node.removeEventListener('keydown', onkeydown);
      if (previous instanceof HTMLElement) previous.focus();
    },
  };
}
