/** The pairing rule, made structural.
 *
 * Every themed string in the product travels with a plain one. The plain half
 * is what a screen reader announces first, what goes in a calendar body, and
 * what a tired person reads at 6am. These helpers exist so a component cannot
 * accidentally render the themed half on its own: `requirePair` throws, loudly,
 * during render rather than shipping a pretty screen nobody can parse.
 */

export interface Paired {
  /** The wizarding-botany wording. Optional — plain-only is always allowed. */
  themed?: string;
  /** The literal meaning. Never optional. */
  plain: string;
}

/** How a component shows the plain half beside its themed half. */
export type PlainDisplay = 'beside' | 'below' | 'screen-reader';

/**
 * Assert the pairing rule for one label.
 *
 * @param themed the themed string, if the caller supplied one
 * @param plain the plain-language string
 * @param where the component name, so the error names the offender
 * @returns the plain string, trimmed
 */
export function requirePair(
  themed: string | undefined,
  plain: string | undefined,
  where: string,
): string {
  const cleanPlain = plain?.trim() ?? '';
  const cleanThemed = themed?.trim() ?? '';
  if (cleanPlain) return cleanPlain;
  if (cleanThemed) {
    throw new Error(
      `${where}: "${cleanThemed}" is a themed string with no plain one. ` +
        'Every themed string is paired with a plain one.',
    );
  }
  throw new Error(`${where}: a plain-language label is required.`);
}

/** True when the themed half is worth rendering at all. */
export function hasThemed(themed: string | undefined): themed is string {
  return Boolean(themed?.trim());
}

/**
 * The single string to hand an `aria-label`, `title` or calendar body: plain
 * first, because that is the half that carries the meaning.
 */
export function plainFirst(themed: string | undefined, plain: string): string {
  return hasThemed(themed) ? `${plain} (${themed.trim()})` : plain;
}
