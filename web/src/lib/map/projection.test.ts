/** The client's half of the calibration arithmetic.
 *
 * The server owns calibration and this module mirrors it, which is the risk
 * worth testing: the two can drift. So the cases here are the same ones
 * `api/grounds/tests/test_grounds_calibration.py` asserts, phrased the same
 * way — control points whose answer is known by construction, fitted and
 * then asked to place themselves back.
 */

import { describe, expect, it } from 'vitest';
import {
  clampToLayer,
  distanceMetres,
  fitSurvey,
  formatMetres,
  isCalibrated,
  isOnLayer,
  metresPerDegree,
  millimetresPerPixel,
  scaleBar,
} from './projection';
import type { CalibrationPoint, MapLayer } from './types';

const ORIGIN_LAT = 39.75;
const ORIGIN_LON = -86.16;
const METRES_PER_PX = 0.1;

function layer(over: Partial<MapLayer> = {}): MapLayer {
  return {
    id: 'layer-1',
    site_id: 'site-1',
    name: 'Ground floor',
    kind: 'floor_plan',
    image_url: '/api/v1/grounds/layers/layer-1/image',
    image_width_px: 1000,
    image_height_px: 1000,
    scale_mm_per_px: null,
    calibration: { scale_mm_per_px: null, points: [] },
    ordinal: 0,
    ...over,
  };
}

/** Two corners of a patch that is square *on the ground*, not in degrees. */
function squarePatch(sizePx = 1000): CalibrationPoint[] {
  const metres = sizePx * METRES_PER_PX;
  const per = metresPerDegree(ORIGIN_LAT);
  return [
    { px: [0, sizePx], world: [ORIGIN_LAT, ORIGIN_LON] },
    {
      px: [sizePx, 0],
      world: [ORIGIN_LAT + metres / per.lat, ORIGIN_LON + metres / per.lon],
    },
  ];
}

describe('fitSurvey', () => {
  it('places its own control points back exactly', () => {
    const points = squarePatch();
    const fit = fitSurvey(points)!;
    for (const point of points) {
      const got = fit.toWorld({ x: point.px[0], y: point.px[1] });
      expect(got.lat).toBeCloseTo(point.world[0], 9);
      expect(got.lon).toBeCloseTo(point.world[1], 9);
    }
  });

  it('inverts', () => {
    const fit = fitSurvey(squarePatch())!;
    for (const px of [
      { x: 0, y: 0 },
      { x: 250, y: 900 },
      { x: 1000, y: 1000 },
    ]) {
      const back = fit.toPx(fit.toWorld(px));
      expect(back.x).toBeCloseTo(px.x, 6);
      expect(back.y).toBeCloseTo(px.y, 6);
    }
  });

  it('keeps north up, though image y grows downward', () => {
    const fit = fitSurvey(squarePatch())!;
    expect(Math.abs(fit.rotationDeg)).toBeLessThan(0.5);
    expect(fit.toWorld({ x: 500, y: 0 }).lat).toBeGreaterThan(fit.toWorld({ x: 500, y: 1000 }).lat);
  });

  it('recovers the scale the points were built at', () => {
    const fit = fitSurvey(squarePatch())!;
    expect(fit.metresPerPx).toBeCloseTo(METRES_PER_PX, 5);
  });

  it('marks a two-point residual as no evidence at all', () => {
    const fit = fitSurvey(squarePatch())!;
    expect(fit.pointCount).toBe(2);
    expect(fit.rmsErrorM).toBeCloseTo(0, 9);
    expect(fit.residualIsMeaningful).toBe(false);
  });

  it('reports a third point that disagrees', () => {
    const exact = squarePatch();
    const per = metresPerDegree(ORIGIN_LAT);
    const points: CalibrationPoint[] = [
      ...exact,
      {
        px: [500, 500],
        world: [
          (exact[0].world[0] + exact[1].world[0]) / 2 + 10 / per.lat,
          (exact[0].world[1] + exact[1].world[1]) / 2,
        ],
      },
    ];
    const fit = fitSurvey(points)!;
    expect(fit.residualIsMeaningful).toBe(true);
    expect(fit.rmsErrorM).toBeGreaterThan(1);
    expect(fit.worstErrorM).toBeGreaterThanOrEqual(fit.rmsErrorM);
  });

  it('returns null rather than throwing while the points are still being placed', () => {
    expect(fitSurvey([])).toBeNull();
    expect(fitSurvey([squarePatch()[0]])).toBeNull();
  });

  it('returns null for points stacked on one pixel', () => {
    expect(
      fitSurvey([
        { px: [10, 10], world: [ORIGIN_LAT, ORIGIN_LON] },
        { px: [10, 10], world: [ORIGIN_LAT + 0.001, ORIGIN_LON] },
      ]),
    ).toBeNull();
  });

  it('returns null for points naming one place on Earth', () => {
    expect(
      fitSurvey([
        { px: [0, 0], world: [ORIGIN_LAT, ORIGIN_LON] },
        { px: [100, 100], world: [ORIGIN_LAT, ORIGIN_LON] },
      ]),
    ).toBeNull();
  });

  it('works in the southern hemisphere', () => {
    const points: CalibrationPoint[] = [
      { px: [0, 100], world: [-41.29, 174.78] },
      { px: [100, 0], world: [-41.289, 174.781] },
    ];
    const fit = fitSurvey(points)!;
    for (const point of points) {
      const got = fit.toWorld({ x: point.px[0], y: point.px[1] });
      expect(got.lat).toBeCloseTo(point.world[0], 9);
      expect(got.lon).toBeCloseTo(point.world[1], 9);
    }
  });
});

describe('isCalibrated', () => {
  it('reads an empty Calibration as "nobody has calibrated this"', () => {
    // The state the design said the contract could not express. It can:
    // an empty object, told apart by the layer's own kind. No null needed.
    expect(isCalibrated('floor_plan', { scale_mm_per_px: null, points: [] })).toBe(false);
    expect(isCalibrated('survey', { scale_mm_per_px: null, points: [] })).toBe(false);
    expect(isCalibrated('floor_plan', null)).toBe(false);
  });

  it('needs a positive scale for a plan', () => {
    expect(isCalibrated('floor_plan', { scale_mm_per_px: 0, points: [] })).toBe(false);
    expect(isCalibrated('floor_plan', { scale_mm_per_px: -1, points: [] })).toBe(false);
    expect(isCalibrated('floor_plan', { scale_mm_per_px: 12.5, points: [] })).toBe(true);
  });

  it('needs two points for a survey, and a scale alone is not enough', () => {
    expect(isCalibrated('survey', { scale_mm_per_px: 12.5, points: [] })).toBe(false);
    expect(isCalibrated('survey', { scale_mm_per_px: null, points: squarePatch() })).toBe(true);
  });
});

describe('millimetresPerPixel', () => {
  it('reads a plan straight off its scale', () => {
    expect(millimetresPerPixel(layer({ scale_mm_per_px: 12.5 }))).toBe(12.5);
  });

  it('derives a survey from its control points rather than trusting the field', () => {
    const survey = layer({
      kind: 'survey',
      scale_mm_per_px: 9999,
      calibration: { scale_mm_per_px: 9999, points: squarePatch() },
    });
    expect(millimetresPerPixel(survey)).toBeCloseTo(METRES_PER_PX * 1000, 1);
  });

  it('is null when nothing knows the scale', () => {
    expect(millimetresPerPixel(layer())).toBeNull();
    expect(millimetresPerPixel(layer({ kind: 'survey' }))).toBeNull();
  });
});

describe('distanceMetres', () => {
  it('converts a pixel span with the layer scale', () => {
    const plan = layer({ scale_mm_per_px: 10 });
    expect(distanceMetres(plan, { x: 0, y: 0 }, { x: 300, y: 400 })).toBeCloseTo(5, 6);
  });

  it('is null on an uncalibrated layer rather than guessing', () => {
    expect(distanceMetres(layer(), { x: 0, y: 0 }, { x: 10, y: 0 })).toBeNull();
  });
});

describe('formatMetres', () => {
  it.each([
    [0.4, '40 cm'],
    [1.25, '1.3 m'],
    [42, '42 m'],
    [2500, '2.50 km'],
  ])('renders %s as %s', (metres, expected) => {
    expect(formatMetres(metres)).toBe(expected);
  });

  it('says so rather than printing NaN', () => {
    expect(formatMetres(Number.NaN)).toBe('an unknown distance');
  });
});

describe('scaleBar', () => {
  it('picks a round number that fits', () => {
    const bar = scaleBar(0.1, 120)!;
    expect([1, 2, 5, 10]).toContain(bar.metres);
    expect(bar.widthPx).toBeLessThanOrEqual(120);
  });

  it('scales with the zoom', () => {
    const close = scaleBar(0.01, 120)!;
    const far = scaleBar(1, 120)!;
    expect(far.metres).toBeGreaterThan(close.metres);
  });

  it('refuses a nonsense scale', () => {
    expect(scaleBar(0)).toBeNull();
    expect(scaleBar(Number.NaN)).toBeNull();
  });
});

describe('clampToLayer', () => {
  it('keeps a point on the sheet, because the server refuses one off it', () => {
    const plan = layer({ image_width_px: 100, image_height_px: 50 });
    expect(clampToLayer(plan, { x: -10, y: 80 })).toEqual({ x: 0, y: 50 });
    expect(clampToLayer(plan, { x: 500, y: -5 })).toEqual({ x: 100, y: 0 });
  });

  it('treats the edge as on the sheet, the same way the server does', () => {
    const plan = layer({ image_width_px: 100, image_height_px: 50 });
    expect(isOnLayer(plan, { x: 0, y: 0 })).toBe(true);
    expect(isOnLayer(plan, { x: 100, y: 50 })).toBe(true);
    expect(isOnLayer(plan, { x: 100.01, y: 50 })).toBe(false);
  });
});
