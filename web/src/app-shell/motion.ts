/** Which navigations get a page transition. The design system, an earlier release.
 *
 * The guide (§18) asks for page transitions that fade with a slight vertical
 * movement. Restraint is the point: only leafing between the facets of one
 * plant — register, tending, compendium, journal — is the "page turn" the
 * guide describes. A jump between sections is a different place, not a next
 * page, and gets none.
 *
 * The decision is here as a plain function so it is testable; the shell calls
 * it from SvelteKit's `onNavigate` and writes the answer onto the document as
 * `data-transition`. The motion itself lives in `base.css`, keyed on that
 * attribute, which is what lets `prefers-reduced-motion` remove it in the
 * stylesheet before any script has run.
 */

export type TransitionKind = 'facet';

const FACET = /^\/specimen\/([^/]+)(?:\/(register|tending|compendium|journal))?\/?$/;

export function transitionKind(
  from: string | null | undefined,
  to: string | null | undefined,
): TransitionKind | null {
  if (!from || !to || from === to) return null;
  const a = FACET.exec(from);
  const b = FACET.exec(to);
  if (!a || !b) return null;
  if (a[1] !== b[1]) return null; // another plant is another book
  return 'facet';
}
