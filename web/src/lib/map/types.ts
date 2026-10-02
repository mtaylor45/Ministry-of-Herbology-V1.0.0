/** The Grounds, as the frozen contract declares it.
 *
 * These mirror `contracts/openapi/openapi.yaml` and change only there
 *. Two of them are worth a note.
 *
 * `MapLayer.calibration` is a bare `$ref` in the contract, so it is never
 * `null` on the wire: an uncalibrated layer serves an **empty** `Calibration`
 * — `{scale_mm_per_px: null, points: []}`. Ask `isCalibrated` rather than
 * truthiness; the object is always there.
 *
 * `Pin.px` *is* nullable, and a null one means the specimen is in the Register
 * but not yet placed. That is a normal state and the list below the map is
 * where it shows up.
 */

export type LayerKind = 'floor_plan' | 'survey';

export interface PixelPoint {
  x: number;
  y: number;
}

export interface CalibrationPoint {
  /** `[x, y]` in layer pixels. */
  px: [number, number];
  /** `[latitude, longitude]` in degrees. */
  world: [number, number];
}

export interface Calibration {
  scale_mm_per_px: number | null;
  points: CalibrationPoint[];
}

export interface MapLayer {
  id: string;
  site_id: string;
  name: string;
  kind: LayerKind;
  image_url: string;
  image_width_px: number;
  image_height_px: number;
  scale_mm_per_px: number | null;
  calibration: Calibration;
  ordinal: number;
}

export interface SpecimenBrief {
  id: string;
  display_name: string;
  is_outdoor: boolean;
  thumb_url: string | null;
}

export interface Pin {
  specimen_id: string;
  layer_id: string;
  px: PixelPoint | null;
  specimen: SpecimenBrief | null;
}

/** A zone drawn on a layer. Read from `GET /locations`; see the README for why
 *  this component cannot yet write one back. */
export interface Zone {
  id: string;
  name: string;
  kind: string;
  is_outdoor: boolean;
  map_layer_id: string | null;
  /** A closed ring of `[x, y]` pairs in layer pixels. */
  boundary_px: [number, number][] | null;
}
