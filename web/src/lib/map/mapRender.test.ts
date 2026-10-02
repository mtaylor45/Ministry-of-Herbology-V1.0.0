/** What the Grounds render, before any browser is involved.
 *
 * These are server renders, the same way the design system tests its library. That
 * matters more here than elsewhere: the claim this component makes is that
 * the pin list is the accessible equivalent of the map, and an equivalent
 * that only exists after Leaflet has loaded and hydrated is not one. If the
 * list is in the server render, it is there for a reader on a slow phone, a
 * reader with JavaScript off, and a crawler.
 */

import { describe, expect, it } from 'vitest';
import { attrs, html, text } from '$ui/render';
import CalibrationPanel from './CalibrationPanel.svelte';
import GroundsMap from './GroundsMap.svelte';
import LayerUpload from './LayerUpload.svelte';
import PinList from './PinList.svelte';
import { pinRows } from './pins';
import type { MapLayer, Pin } from './types';

function layer(over: Partial<MapLayer> = {}): MapLayer {
  return {
    id: 'plan',
    site_id: 'site',
    name: 'Ground floor',
    kind: 'floor_plan',
    image_url: '/api/v1/grounds/layers/plan/image',
    image_width_px: 900,
    image_height_px: 600,
    scale_mm_per_px: null,
    calibration: { scale_mm_per_px: null, points: [] },
    ordinal: 0,
    ...over,
  };
}

/** What the API serves for a calibrated plan: the scale on the layer *and*
 *  inside its `Calibration`, which is the pair the server writes together. */
function calibratedPlan(): MapLayer {
  return layer({
    scale_mm_per_px: 12.5,
    calibration: { scale_mm_per_px: 12.5, points: [] },
  });
}

const PINS: Pin[] = [
  {
    specimen_id: 'sp-1',
    layer_id: 'plan',
    px: { x: 50, y: 50 },
    specimen: { id: 'sp-1', display_name: 'Gilderoy', is_outdoor: false, thumb_url: null },
  },
  {
    specimen_id: 'sp-2',
    layer_id: 'plan',
    px: null,
    specimen: { id: 'sp-2', display_name: 'Bramble', is_outdoor: true, thumb_url: null },
  },
];

describe('PinList', () => {
  const markup = html(PinList as never, { layer: layer(), rows: pinRows(layer(), PINS) });

  it('gives every pin a real link to its Specimen page', () => {
    // The earlier exit criterion, reached by keyboard rather than by pointing.
    expect(markup).toContain('href="/specimen/sp-1/register"');
    expect(markup).toContain('href="/specimen/sp-2/register"');
  });

  it('describes where each pin is in words, not in pixels', () => {
    expect(text(markup)).toContain('upper left of Ground floor');
    expect(text(markup)).not.toMatch(/\b50,\s*50\b/);
  });

  it('lists a plant that is not placed yet instead of hiding it', () => {
    expect(text(markup)).toContain('Bramble');
    expect(text(markup)).toContain('Not yet placed on Ground floor');
    expect(text(markup)).toContain('Awaiting a place');
  });

  it('pairs every themed heading with a plain one', () => {
    const readable = text(markup);
    expect(readable).toContain('The Roll of Plantings');
    expect(readable).toContain('Every pin on Ground floor, as a list');
    expect(readable).toContain('Awaiting a place');
    expect(readable).toContain('in the Register, not yet on Ground floor');
  });

  it('announces each pin as one of a known number — of the placed ones', () => {
    // One of these two plants is placed, so "1 of 1". Counting the unplaced
    // one would promise a second pin on the sheet that is not there.
    expect(text(markup)).toContain('pin 1 of 1');
  });

  it('offers a keyboard route to move and to lift a pin', () => {
    const readable = text(markup);
    expect(readable).toContain('Move pin');
    expect(readable).toContain('Lift pin off the map');
    expect(readable).toContain('Place on the map');
  });

  it('is a landmark with a name, not an anonymous div', () => {
    expect(markup).toContain('aria-labelledby="pin-list-heading"');
  });

  it('says so when nothing is pinned, rather than rendering an empty list', () => {
    const empty = html(PinList as never, { layer: layer(), rows: [] });
    expect(text(empty)).toContain('Nothing is pinned to Ground floor yet');
  });
});

describe('GroundsMap', () => {
  const markup = html(GroundsMap as never, {
    layer: layer(),
    rows: pinRows(layer(), PINS),
  });

  it('renders without Leaflet, because Leaflet needs a window', () => {
    expect(markup).toContain('role="application"');
  });

  it('names itself and points at its own summary', () => {
    const canvas = attrs(markup, 'div');
    expect(markup).toContain('aria-label="Map of Ground floor"');
    expect(markup).toContain('aria-describedby="map-summary"');
    expect(canvas).toBeTruthy();
  });

  it('tells a reader up front that the list carries the same pins', () => {
    expect(text(markup)).toContain('1 plant placed');
    expect(text(markup)).toContain('The list below carries the same pins');
  });

  it('is reachable by keyboard', () => {
    expect(markup).toContain('tabindex="0"');
  });

  it('admits when there is no scale rather than drawing a bar that lies', () => {
    expect(text(markup)).toContain('not calibrated, so distances on it are unknown');
  });

  it('carries a live region for the placement announcements', () => {
    expect(markup).toContain('aria-live="polite"');
  });

  it('offers zone drawing as a pressed-state toggle', () => {
    expect(markup).toContain('aria-pressed="false"');
    expect(text(markup)).toContain('Draw a zone');
  });
});

describe('CalibrationPanel', () => {
  it('asks a floor plan for a scale and a survey for control points', () => {
    const plan = text(html(CalibrationPanel as never, { layer: layer() }));
    expect(plan).toContain('Millimetres per pixel');
    expect(plan).not.toContain('Latitude, in degrees');

    const survey = text(
      html(CalibrationPanel as never, { layer: layer({ kind: 'survey', name: 'Plat' }) }),
    );
    expect(survey).toContain('Latitude, in degrees');
    expect(survey).not.toContain('Millimetres per pixel');
  });

  it('says plainly whether the layer is calibrated', () => {
    expect(text(html(CalibrationPanel as never, { layer: layer() }))).toContain(
      'is not calibrated yet',
    );
    expect(text(html(CalibrationPanel as never, { layer: calibratedPlan() }))).toContain(
      'is calibrated',
    );
  });

  it('refuses to present a two-point fit as evidence of accuracy', () => {
    const survey = layer({
      kind: 'survey',
      calibration: {
        scale_mm_per_px: null,
        points: [
          { px: [0, 100], world: [39.75, -86.16] },
          { px: [100, 0], world: [39.751, -86.1588] },
        ],
      },
    });
    const markup = text(html(CalibrationPanel as never, { layer: survey }));
    expect(markup).toContain('Two points always fit exactly');
    expect(markup).toContain('Add a third point');
  });

  it('warns that recalibrating re-places every pin', () => {
    const markup = text(html(CalibrationPanel as never, { layer: calibratedPlan() }));
    expect(markup).toContain('re-places every pin');
  });
});

describe('LayerUpload', () => {
  const markup = html(LayerUpload as never, {});

  it('accepts exactly what the design accepts, and says so before refusing', () => {
    expect(markup).toContain('accept="image/png,image/jpeg"');
    expect(text(markup)).toContain('a PNG or a JPEG');
  });

  it('explains the PDF case rather than leaving it to a 415', () => {
    expect(text(markup)).toContain('A PDF plat has to be exported as a PNG or JPEG');
  });

  it('labels its file input, which is the control everything already handles', () => {
    expect(markup).toContain('for="layer-file"');
    expect(markup).toContain('id="layer-file"');
    expect(markup).toContain('aria-describedby="file-hint"');
  });

  it("separates the deployment's problems from the person's", () => {
    const operators = html(LayerUpload as never, {
      error: 'The volume holding map layers is full.',
      operatorProblem: true,
    });
    expect(text(operators)).toContain('This is the deployment, not the file');

    const theirs = html(LayerUpload as never, {
      error: 'A map layer must be a PNG or a JPEG image.',
      operatorProblem: false,
    });
    expect(text(theirs)).not.toContain('This is the deployment');
    expect(text(theirs)).toContain('must be a PNG or a JPEG');
  });

  it('pairs its themed heading with a plain one', () => {
    expect(text(markup)).toContain('Lodging a Plan');
    expect(text(markup)).toContain('Upload a floor plan or a property survey');
  });
});
