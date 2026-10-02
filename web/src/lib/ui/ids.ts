/** Stable-enough ids for label/control wiring.
 *
 * Svelte's `$props.id()` is the right tool inside a component; this is for the
 * odd place that needs an id outside one (and for tests).
 */

let counter = 0;

export function uid(prefix = 'moh'): string {
  counter += 1;
  return `${prefix}-${counter.toString(36)}`;
}

/** Join the ids a control should point `aria-describedby` at, dropping blanks. */
export function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  const kept = ids.filter((id): id is string => Boolean(id));
  return kept.length ? kept.join(' ') : undefined;
}
