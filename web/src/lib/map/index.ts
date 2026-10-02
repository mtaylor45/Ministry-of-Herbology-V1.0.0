/** The Grounds: maps, calibration and pins. The maps module.
 *
 * Import from `$map`:
 *
 *     import { Grounds } from '$map';
 *
 * `Grounds` is the whole surface — layer switcher, map, pin list, calibration
 * and upload — so a route can be one element and the app's screens's releases is
 * about the Specimen cross-links rather than about rebuilding this. The parts
 * are exported too, for a screen that wants only one of them.
 */

export { default as CalibrationPanel } from './CalibrationPanel.svelte';
export { default as Grounds } from './Grounds.svelte';
export { default as GroundsMap } from './GroundsMap.svelte';
export { default as LayerUpload } from './LayerUpload.svelte';
export { default as PinList } from './PinList.svelte';

export {
  GroundsError,
  isOperatorProblem,
  listLayers,
  listPins,
  listZones,
  setCalibration,
  setPin,
  uploadLayer,
} from './client';

export {
  displayName,
  layerSummary,
  pinRows,
  positionSentence,
  quadrantOf,
  specimenHref,
  unplaced,
  type PinRow,
} from './pins';

export {
  ARROWS,
  COARSE_STEP,
  FINE_STEP,
  isArrow,
  movementAnnouncement,
  nudge,
  round,
  startingPoint,
  type Arrow,
} from './placement';

export {
  clampToLayer,
  distanceMetres,
  fitSurvey,
  formatMetres,
  isCalibrated,
  isOnLayer,
  metresPerDegree,
  millimetresPerPixel,
  scaleBar,
  type SurveyFit,
} from './projection';

export type {
  Calibration,
  CalibrationPoint,
  LayerKind,
  MapLayer,
  Pin,
  PixelPoint,
  SpecimenBrief,
  Zone,
} from './types';
