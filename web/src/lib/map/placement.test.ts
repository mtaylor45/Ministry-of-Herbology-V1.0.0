/** Placing a pin with no pointer.
 *
 * The definition of done again: dragging a marker is unavailable to anyone working by
 * keyboard. These are the numbers behind the alternative — a crosshair that
 * arrow keys move and Enter commits — and they are tested here rather than in
 * the component so the map's click handler and the keyboard handler cannot
 * end up with different ideas of where the sheet ends.
 */

import { describe, expect, it } from 'vitest';
import {
  ARROWS,
  COARSE_STEP,
  FINE_STEP,
  isArrow,
  movementAnnouncement,
  nudge,
  round,
  startingPoint,
} from './placement';
import { quadrantOf } from './pins';
import type { MapLayer } from './types';

const plan: MapLayer = {
  id: 'plan',
  site_id: 'site',
  name: 'Ground floor',
  kind: 'floor_plan',
  image_url: '/x',
  image_width_px: 1000,
  image_height_px: 500,
  scale_mm_per_px: null,
  calibration: { scale_mm_per_px: null, points: [] },
  ordinal: 0,
};

describe('startingPoint', () => {
  it('starts on the pin when there is one', () => {
    expect(startingPoint(plan, { x: 10, y: 20 })).toEqual({ x: 10, y: 20 });
  });

  it('starts in the middle when there is not', () => {
    expect(startingPoint(plan, null)).toEqual({ x: 500, y: 250 });
  });

  it('pulls a stale pin back onto the sheet', () => {
    expect(startingPoint(plan, { x: 99999, y: -5 })).toEqual({ x: 1000, y: 0 });
  });
});

describe('nudge', () => {
  it('steps by a fraction of the sheet, so a big plat is not unusable', () => {
    const from = { x: 500, y: 250 };
    expect(nudge(plan, from, 'ArrowRight')).toEqual({
      x: 500 + 1000 * COARSE_STEP,
      y: 250,
    });
    expect(nudge(plan, from, 'ArrowDown').y).toBe(250 + 500 * COARSE_STEP);
  });

  it('moves up when ArrowUp is pressed, though image y grows downward', () => {
    expect(nudge(plan, { x: 500, y: 250 }, 'ArrowUp').y).toBeLessThan(250);
  });

  it('takes a finer step with Shift', () => {
    const coarse = nudge(plan, { x: 500, y: 250 }, 'ArrowRight').x;
    const fine = nudge(plan, { x: 500, y: 250 }, 'ArrowRight', true).x;
    expect(fine).toBeLessThan(coarse);
    expect(fine).toBe(500 + 1000 * FINE_STEP);
  });

  it('never walks off the sheet', () => {
    let point = { x: 0, y: 0 };
    for (let i = 0; i < 100; i += 1) point = nudge(plan, point, 'ArrowLeft');
    expect(point).toEqual({ x: 0, y: 0 });

    point = { x: 1000, y: 500 };
    for (let i = 0; i < 100; i += 1) point = nudge(plan, point, 'ArrowDown');
    expect(point).toEqual({ x: 1000, y: 500 });
  });

  it('knows its own arrows', () => {
    for (const key of ARROWS) expect(isArrow(key)).toBe(true);
    expect(isArrow('Enter')).toBe(false);
    expect(isArrow('a')).toBe(false);
  });
});

describe('round', () => {
  it('keeps two decimals, which is finer than any screen', () => {
    expect(round({ x: 1.23456, y: 9.87654 })).toEqual({ x: 1.23, y: 9.88 });
  });
});

describe('movementAnnouncement', () => {
  it('says the quadrant, never the coordinates', () => {
    const said = movementAnnouncement(plan, { x: 50, y: 50 }, quadrantOf);
    expect(said).toContain('upper left');
    expect(said).not.toContain('50');
  });

  it('says when the crosshair has stopped against an edge', () => {
    expect(movementAnnouncement(plan, { x: 0, y: 250 }, quadrantOf)).toContain(
      'against the left edge',
    );
    expect(movementAnnouncement(plan, { x: 0, y: 0 }, quadrantOf)).toContain(
      'against the left and top edge',
    );
  });
});
