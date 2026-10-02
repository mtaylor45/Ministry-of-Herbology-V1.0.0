/** The chart's colours, read from the theme rather than written down.
 *
 * uPlot draws to a canvas, and a canvas cannot inherit a CSS variable: every
 * stroke needs a concrete colour at the moment it is drawn. So the colours are
 * *read* from the computed `--moh-*` tokens on the element the chart lives in.
 *
 * That is the whole point. the design re-pigments every token — new
 * palette, new display face, light as the default — and a hex written into a
 * chart here would survive it and quietly stop matching the app around it.
 * Nothing in this file names a colour, a size or a duration.
 */

/** A token's computed value, or the element's own ink when the token is
 *  missing. Never a literal: an unstyled chart inherits rather than invents. */
export function token(element: Element, name: string): string {
  const styles = getComputedStyle(element);
  const value = styles.getPropertyValue(name).trim();
  return value || styles.color;
}

/** `--moh-text-sm` and friends are in rem; a canvas font needs pixels. */
export function remToPx(value: string, rootPx: number): number | null {
  const match = /^(-?[\d.]+)(rem|em|px)$/.exec(value.trim());
  if (!match) return null;
  const size = Number(match[1]);
  if (!Number.isFinite(size)) return null;
  return match[2] === 'px' ? size : size * rootPx;
}

/** The font shorthand a canvas axis needs, assembled from the body tokens. */
export function axisFont(element: Element, rootPx: number): string {
  const styles = getComputedStyle(element);
  const family = styles.getPropertyValue('--moh-font-body').trim() || styles.fontFamily;
  const size = remToPx(styles.getPropertyValue('--moh-text-sm'), rootPx) ?? rootPx * 0.8;
  return `${Math.round(size)}px ${family}`;
}

/** One plotted line or bar, named in words before it is drawn in a colour.
 *
 *  `dash` is not decoration: two lines that differ only by hue fail WCAG 1.4.1
 *  and fail anybody reading the screen in direct sun, which is where this app
 *  is used. Every series here is told apart by shape as well as by colour, and
 *  by its label in the table beneath. */
export interface ChartSeries {
  /** Plain-language name. Shown in the legend and read aloud. */
  plain: string;
  /** The `--moh-*` token this series is drawn in. */
  colorToken: string;
  /** Dashed, so two series are distinguishable without colour. */
  dash?: boolean;
  /** Draw as bars rather than a line — rainfall reads as quantity, not trend. */
  bars?: boolean;
  /** Fill under the line, faintly. */
  fill?: boolean;
}
