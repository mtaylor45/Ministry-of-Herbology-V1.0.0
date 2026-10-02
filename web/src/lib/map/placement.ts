/** Placing a pin without a pointer.
 *
 * Dragging a marker is the obvious gesture and it is unavailable to anyone
 * working by keyboard, so placement here is a mode rather than a drag: pick a
 * plant, the crosshair appears at the middle of the sheet (or on the pin, if
 * there already is one), arrow keys move it, Enter commits and Escape leaves
 * it where it was.
 *
 * The arithmetic lives here rather than in the component so it can be tested
 * without a browser, and so the map's click handler and the keyboard handler
 * cannot disagree about where the edge of the sheet is.
 */

import { clampToLayer } from './projection';
import type { MapLayer, PixelPoint } from './types';

/** A coarse step and a fine one, as a fraction of the sheet.
 *
 * Fractions rather than pixels: one step should cross a 400px plan and a
 * 4000px plat in about the same number of presses, or the big sheet is
 * unusable and the small one is unmanageable.
 */
export const COARSE_STEP = 0.05;
export const FINE_STEP = 0.005;

export type Arrow = 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight';

export const ARROWS: readonly Arrow[] = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];

export function isArrow(key: string): key is Arrow {
  return (ARROWS as readonly string[]).includes(key);
}

/** Where the crosshair starts: on the existing pin, else the middle. */
export function startingPoint(layer: MapLayer, existing: PixelPoint | null): PixelPoint {
  if (existing) return clampToLayer(layer, existing);
  return { x: layer.image_width_px / 2, y: layer.image_height_px / 2 };
}

/** Move the crosshair one step, never off the sheet.
 *
 * `fine` is the Shift modifier. Image y grows downward, so ArrowUp subtracts.
 */
export function nudge(layer: MapLayer, from: PixelPoint, key: Arrow, fine = false): PixelPoint {
  const fraction = fine ? FINE_STEP : COARSE_STEP;
  const stepX = layer.image_width_px * fraction;
  const stepY = layer.image_height_px * fraction;
  const moved = { ...from };
  if (key === 'ArrowUp') moved.y -= stepY;
  if (key === 'ArrowDown') moved.y += stepY;
  if (key === 'ArrowLeft') moved.x -= stepX;
  if (key === 'ArrowRight') moved.x += stepX;
  return clampToLayer(layer, round(moved));
}

/** Pixels are whole-ish: two decimals is finer than any screen and keeps the
 *  numbers in the announcement readable. */
export function round(point: PixelPoint): PixelPoint {
  return { x: Math.round(point.x * 100) / 100, y: Math.round(point.y * 100) / 100 };
}

/** What the live region says after each move. Quadrant, not coordinates:
 *  "412, 388" tells a listener nothing they can act on. */
export function movementAnnouncement(
  layer: MapLayer,
  point: PixelPoint,
  quadrant: (layer: MapLayer, px: PixelPoint) => string,
): string {
  const atLeft = point.x <= 0;
  const atRight = point.x >= layer.image_width_px;
  const atTop = point.y <= 0;
  const atBottom = point.y >= layer.image_height_px;
  const edges = [atLeft && 'left', atRight && 'right', atTop && 'top', atBottom && 'bottom'].filter(
    Boolean,
  ) as string[];
  const where = quadrant(layer, point);
  if (edges.length) return `${where}, against the ${edges.join(' and ')} edge`;
  return where;
}
