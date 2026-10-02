/** Batch selection state, shared by every list that supports batch completion.
 *
 * Morning Rounds completes tasks one tap at a time and in batches; the
 * select-all control needs a third state for "some", and checkboxes express
 * that as `indeterminate`. This is the one place that maths lives, so the app's screens and the design system
 * cannot disagree about it.
 */

export type CheckState = 'unchecked' | 'mixed' | 'checked';

/**
 * What a tick in a list actually means.
 *
 * `completion` — the tick is the act: the row is done, struck through, over.
 * `selection` — the tick gathers the row for a batch and the completion happens
 * somewhere else. Morning Rounds needs this one: attribution is chosen at
 * completion, so the tick cannot be the completion, and a row struck
 * through before anybody has done anything is a lie in the most-used control in
 * the app.
 */
export type CheckMeaning = 'completion' | 'selection';

/** The word a ticked row shows for each meaning. Never colour alone. */
export const CHECKED_PLAIN: Record<CheckMeaning, string> = {
  completion: 'Done',
  selection: 'Selected',
};

/** What the select-all control shows for a selection of `selected` out of `total`. */
export function selectionState(selected: number, total: number): CheckState {
  if (total <= 0 || selected <= 0) return 'unchecked';
  if (selected >= total) return 'checked';
  return 'mixed';
}

/** What a select-all tap does next: anything short of "all" selects all. */
export function nextSelectAll(state: CheckState): boolean {
  return state !== 'checked';
}

/** Apply a select-all tap to a set of ids. */
export function toggleAll<T>(ids: readonly T[], state: CheckState): Set<T> {
  return nextSelectAll(state) ? new Set(ids) : new Set<T>();
}

/** Apply a single-row tap to a selection. Returns a new set; never mutates. */
export function toggleOne<T>(selection: ReadonlySet<T>, id: T): Set<T> {
  const next = new Set(selection);
  if (!next.delete(id)) next.add(id);
  return next;
}

/** The plain-language summary a batch bar announces. Never colour alone. */
export function selectionSummary(selected: number, total: number): string {
  if (selected <= 0) return `Nothing selected of ${total}`;
  return `${selected} of ${total} selected`;
}
