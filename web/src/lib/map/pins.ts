/** Pins as data, so the map and the list cannot tell different stories.
 *
 * **A pin reachable only by pointing is unreachable by keyboard and invisible
 * to a screen reader.** The answer this component ships is a list — not a
 * fallback bolted on beside the map, but the same array of rows the markers
 * are drawn from, rendered twice. Everything a marker can do (open the
 * Specimen page, be moved, be lifted) a row can do, and the words in the row
 * come from here, so a marker cannot acquire behaviour the list lacks.
 *
 * The position sentence is the part worth explaining. "At 412, 388" is a fact
 * about a raster, not a place; what somebody actually needs to hear is which
 * part of the sheet the plant is on and, when the layer is calibrated, how
 * far in it is. So a pin describes itself as "upper left of Ground floor,
 * about 4 m in from the left edge" — and an unplaced pin says so plainly
 * rather than being left out.
 */

import { formatMetres, millimetresPerPixel } from './projection';
import type { MapLayer, Pin, PixelPoint } from './types';

/** Where a pin's Specimen page is. The earlier exit criterion runs through here. */
export function specimenHref(specimenId: string): string {
  return `/specimen/${specimenId}/register`;
}

export function displayName(pin: Pin): string {
  return pin.specimen?.display_name?.trim() || 'Unnamed specimen';
}

const VERTICAL = ['upper', 'middle', 'lower'] as const;
const HORIZONTAL = ['left', 'centre', 'right'] as const;

function third(value: number, extent: number): 0 | 1 | 2 {
  if (extent <= 0) return 1;
  const fraction = value / extent;
  if (fraction < 1 / 3) return 0;
  if (fraction < 2 / 3) return 1;
  return 2;
}

/** "upper left", "middle centre", "lower right" — a 3×3 reading of the sheet. */
export function quadrantOf(layer: MapLayer, px: PixelPoint): string {
  const row = VERTICAL[third(px.y, layer.image_height_px)];
  const column = HORIZONTAL[third(px.x, layer.image_width_px)];
  return row === 'middle' && column === 'centre' ? 'the middle' : `${row} ${column}`;
}

/** The sentence a screen reader hears in place of seeing the pin. */
export function positionSentence(layer: MapLayer, px: PixelPoint | null): string {
  if (!px) return `Not yet placed on ${layer.name}`;
  const where = `${quadrantOf(layer, px)} of ${layer.name}`;
  const mmPerPx = millimetresPerPixel(layer);
  if (mmPerPx === null) {
    return `${where}. ${layer.name} is not calibrated, so there is no distance to give.`;
  }
  const fromLeft = formatMetres((px.x * mmPerPx) / 1000);
  const fromTop = formatMetres((px.y * mmPerPx) / 1000);
  return `${where}, about ${fromLeft} in from the left edge and ${fromTop} down from the top.`;
}

export interface PinRow {
  specimenId: string;
  layerId: string;
  name: string;
  px: PixelPoint | null;
  placed: boolean;
  isOutdoor: boolean;
  href: string;
  /** What the marker's `alt` and the list row's `aria-label` both say. */
  label: string;
  position: string;
  /** 1-based among the *placed* pins, as it is announced: "pin 3 of 12".
   *  Zero for an unplaced plant, which is not one of a numbered set. */
  ordinal: number;
  /** How many pins are placed on this layer. */
  total: number;
}

/** Turn the pins of one layer into the rows the map and the list share.
 *
 * Placed pins first, then by name. Two reasons, and both are about the list
 * rather than the map: a reading order you cannot predict is one you cannot
 * use, and the numbering announced to a screen reader ("pin 3 of 12") has to
 * match the order the rows are actually read in — a row that reads first and
 * announces itself as the last of two is worse than no number at all.
 *
 * `total` therefore counts the placed pins only. An unplaced plant is still
 * in the array, because it is the thing somebody opened this screen to fix,
 * but it is not one of a numbered set and does not claim to be.
 */
export function pinRows(layer: MapLayer, pins: readonly Pin[]): PinRow[] {
  const mine = pins
    .filter((pin) => pin.layer_id === layer.id)
    .slice()
    .sort((a, b) => {
      const placed = Number(b.px !== null) - Number(a.px !== null);
      return placed !== 0 ? placed : displayName(a).localeCompare(displayName(b));
    });
  const placedCount = mine.filter((pin) => pin.px !== null).length;

  return mine.map((pin, index) => {
    const name = displayName(pin);
    const position = positionSentence(layer, pin.px);
    const placed = pin.px !== null;
    return {
      specimenId: pin.specimen_id,
      layerId: pin.layer_id,
      name,
      px: pin.px,
      placed,
      isOutdoor: pin.specimen?.is_outdoor ?? false,
      href: specimenHref(pin.specimen_id),
      label: `${name} — ${position}`,
      position,
      ordinal: placed ? index + 1 : 0,
      total: placedCount,
    };
  });
}

/** Specimens the Register holds that this layer has no pin for.
 *
 * The map's job is not only to show what is placed. A plant nobody has
 * pinned is exactly the thing somebody opened this screen to fix, so it is
 * listed rather than omitted.
 */
export function unplaced(
  register: readonly { id: string; display_name?: string; nickname?: string | null }[],
  pins: readonly Pin[],
): { id: string; name: string }[] {
  const pinned = new Set(pins.filter((pin) => pin.px !== null).map((pin) => pin.specimen_id));
  return register
    .filter((specimen) => !pinned.has(specimen.id))
    .map((specimen) => ({
      id: specimen.id,
      name: (specimen.display_name || specimen.nickname || 'Unnamed specimen').trim(),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** A one-line summary for the region that wraps the map, announced on load. */
export function layerSummary(layer: MapLayer, rows: readonly PinRow[]): string {
  const placed = rows.filter((row) => row.placed).length;
  const plants = placed === 1 ? '1 plant' : `${placed} plants`;
  return `${layer.name}: ${plants} placed. The list below carries the same pins.`;
}
