/** Pixels, millimetres and degrees.
 *
 * The server owns calibration: it validates the control points and fits the
 * transform (`api/grounds/domain.py`). This module is the client's half of the
 * same arithmetic, and it exists for three jobs the server cannot do for the
 * map — drawing a scale bar, telling somebody in words how far apart two
 * clicks are, and showing what a survey pin's coordinates actually come out
 * as while they are still placing the control points.
 *
 * The fit is the same one: a similarity transform (scale, rotation,
 * translation) from layer pixels into a local tangent plane in metres. The
 * pixel side is conjugated on the way in because image y grows downward while
 * north grows up, and that single flip is what lets one complex coefficient
 * carry scale and rotation with no reflection term.
 *
 * Keeping the two in step is the risk, so `projection.test.ts` checks this
 * implementation against control points whose answer is known by construction
 * — the same way `test_grounds_calibration.py` checks the server's.
 */

import type { Calibration, CalibrationPoint, LayerKind, MapLayer, PixelPoint } from './types';

/** Metres per degree of latitude and of longitude, at a given latitude. */
export function metresPerDegree(latitudeDeg: number): { lat: number; lon: number } {
  const phi = (latitudeDeg * Math.PI) / 180;
  return {
    lat: 111132.92 - 559.82 * Math.cos(2 * phi) + 1.175 * Math.cos(4 * phi),
    lon: 111412.84 * Math.cos(phi) - 93.5 * Math.cos(3 * phi),
  };
}

export interface SurveyFit {
  originLat: number;
  originLon: number;
  /** The similarity coefficient, in metres per pixel, as `{re, im}`. */
  scaleRotation: { re: number; im: number };
  offsetEastM: number;
  offsetNorthM: number;
  pointCount: number;
  metresPerPx: number;
  rotationDeg: number;
  rmsErrorM: number;
  worstErrorM: number;
  /** False with exactly two points, which fit exactly and prove nothing. */
  residualIsMeaningful: boolean;
  toWorld(px: PixelPoint): { lat: number; lon: number };
  toPx(world: { lat: number; lon: number }): PixelPoint;
}

/** Fit a survey's control points, or return `null` if they cannot be fitted.
 *
 * Returning `null` rather than throwing is deliberate: this runs while
 * somebody is still clicking points, so "not yet" is the common case and not
 * an error worth an exception.
 */
export function fitSurvey(points: readonly CalibrationPoint[]): SurveyFit | null {
  if (points.length < 2) return null;

  const originLat = points.reduce((sum, p) => sum + p.world[0], 0) / points.length;
  const originLon = points.reduce((sum, p) => sum + p.world[1], 0) / points.length;
  const per = metresPerDegree(originLat);

  const pixel = points.map((p) => ({ re: p.px[0], im: -p.px[1] }));
  const world = points.map((p) => ({
    re: (p.world[1] - originLon) * per.lon,
    im: (p.world[0] - originLat) * per.lat,
  }));

  const mean = (values: { re: number; im: number }[]) => ({
    re: values.reduce((sum, v) => sum + v.re, 0) / values.length,
    im: values.reduce((sum, v) => sum + v.im, 0) / values.length,
  });
  const pixelMean = mean(pixel);
  const worldMean = mean(world);

  let numeratorRe = 0;
  let numeratorIm = 0;
  let denominator = 0;
  for (let i = 0; i < points.length; i += 1) {
    const p = { re: pixel[i].re - pixelMean.re, im: pixel[i].im - pixelMean.im };
    const w = { re: world[i].re - worldMean.re, im: world[i].im - worldMean.im };
    // w * conj(p)
    numeratorRe += w.re * p.re + w.im * p.im;
    numeratorIm += w.im * p.re - w.re * p.im;
    denominator += p.re * p.re + p.im * p.im;
  }
  if (denominator === 0) return null;

  const a = { re: numeratorRe / denominator, im: numeratorIm / denominator };
  if (a.re === 0 && a.im === 0) return null;

  const offsetEastM = worldMean.re - (a.re * pixelMean.re - a.im * pixelMean.im);
  const offsetNorthM = worldMean.im - (a.re * pixelMean.im + a.im * pixelMean.re);

  const forward = (x: number, y: number) => {
    const p = { re: x, im: -y };
    return {
      re: a.re * p.re - a.im * p.im + offsetEastM,
      im: a.re * p.im + a.im * p.re + offsetNorthM,
    };
  };

  const residuals = points.map((point, index) => {
    const got = forward(point.px[0], point.px[1]);
    return Math.hypot(got.re - world[index].re, got.im - world[index].im);
  });
  const rms = Math.sqrt(residuals.reduce((sum, r) => sum + r * r, 0) / residuals.length);

  const magnitude = Math.hypot(a.re, a.im);

  return {
    originLat,
    originLon,
    scaleRotation: a,
    offsetEastM,
    offsetNorthM,
    pointCount: points.length,
    metresPerPx: magnitude,
    rotationDeg: (Math.atan2(a.im, a.re) * 180) / Math.PI,
    rmsErrorM: rms,
    worstErrorM: Math.max(...residuals),
    residualIsMeaningful: points.length > 2,
    toWorld({ x, y }) {
      const q = forward(x, y);
      return { lat: originLat + q.im / per.lat, lon: originLon + q.re / per.lon };
    },
    toPx({ lat, lon }) {
      const q = { re: (lon - originLon) * per.lon, im: (lat - originLat) * per.lat };
      const d = { re: q.re - offsetEastM, im: q.im - offsetNorthM };
      const norm = a.re * a.re + a.im * a.im;
      const p = {
        re: (d.re * a.re + d.im * a.im) / norm,
        im: (d.im * a.re - d.re * a.im) / norm,
      };
      return { x: p.re, y: -p.im };
    },
  };
}

/** Whether a layer can place anything yet.
 *
 * The same rule the server applies, and the reason this component never needs
 * `MapLayer.calibration` to be nullable: the empty object is unambiguous once
 * you know the layer's kind, and the layer always carries its kind.
 */
export function isCalibrated(kind: LayerKind, calibration: Calibration | null): boolean {
  if (!calibration) return false;
  if (kind === 'floor_plan') {
    const scale = calibration.scale_mm_per_px;
    return typeof scale === 'number' && Number.isFinite(scale) && scale > 0;
  }
  return (calibration.points?.length ?? 0) >= 2;
}

/** Millimetres of ground per pixel, whichever way the layer knows it. */
export function millimetresPerPixel(layer: MapLayer): number | null {
  if (layer.kind === 'floor_plan') {
    const scale = layer.scale_mm_per_px;
    return typeof scale === 'number' && scale > 0 ? scale : null;
  }
  const fit = fitSurvey(layer.calibration?.points ?? []);
  if (fit) return fit.metresPerPx * 1000;
  const declared = layer.scale_mm_per_px;
  return typeof declared === 'number' && declared > 0 ? declared : null;
}

/** How far apart two points on a layer are, in metres — or `null` uncalibrated. */
export function distanceMetres(layer: MapLayer, a: PixelPoint, b: PixelPoint): number | null {
  const mmPerPx = millimetresPerPixel(layer);
  if (mmPerPx === null) return null;
  return (Math.hypot(b.x - a.x, b.y - a.y) * mmPerPx) / 1000;
}

/** SI internally, and a sentence a person reads (the project conventions: units are SI). */
export function formatMetres(metres: number): string {
  if (!Number.isFinite(metres)) return 'an unknown distance';
  if (metres < 1) return `${Math.round(metres * 100)} cm`;
  if (metres < 10) return `${metres.toFixed(1)} m`;
  if (metres < 1000) return `${Math.round(metres)} m`;
  return `${(metres / 1000).toFixed(2)} km`;
}

/** A round number of metres that fits inside `maxPx` screen pixels.
 *
 * The bar is the only honest way to show a floor plan's scale, because
 * `CRS.Simple` has no latitude to hang a standard scale control on.
 */
export function scaleBar(
  metresPerScreenPx: number,
  maxPx = 120,
): { metres: number; widthPx: number } | null {
  if (!Number.isFinite(metresPerScreenPx) || metresPerScreenPx <= 0) return null;
  const target = metresPerScreenPx * maxPx;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  for (const step of [5, 2, 1]) {
    const metres = step * magnitude;
    if (metres <= target) {
      return { metres, widthPx: metres / metresPerScreenPx };
    }
  }
  const metres = magnitude / 2;
  return { metres, widthPx: metres / metresPerScreenPx };
}

/** Clamp a point to the sheet. The server refuses one off the edge, so the
 *  map does not offer to send one. */
export function clampToLayer(layer: MapLayer, point: PixelPoint): PixelPoint {
  return {
    x: Math.min(Math.max(point.x, 0), layer.image_width_px),
    y: Math.min(Math.max(point.y, 0), layer.image_height_px),
  };
}

export function isOnLayer(layer: MapLayer, point: PixelPoint): boolean {
  return (
    point.x >= 0 &&
    point.y >= 0 &&
    point.x <= layer.image_width_px &&
    point.y <= layer.image_height_px
  );
}
