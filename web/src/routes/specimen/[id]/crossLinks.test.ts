/** The Specimen → map direction of the earlier cross-link.
 *
 * The maps module's direction (pin → Specimen page) is asserted in `web/src/lib/map/`. This
 * suite covers the way back, and most of it is about the states that are *not*
 * "it is pinned here" — those are the ones a screen quietly gets wrong.
 *
 * Layers, pins and specimens are built here rather than read out of
 * `fixtures/`. Nothing below encodes a value from a directory this
 * parts of the project does not own.
 */

import { describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import type { MapLayer, Pin } from '$map';
import WhereOnMap from './WhereOnMap.svelte';
import type { LocationRef, SpecimenDetail } from './api';
import { groundsHref, place } from './mapPlace';

const SPECIMEN_ID = '01890040-0000-7000-8000-00000000cc01';
const PLAN_ID = '01890070-0000-7000-8000-00000000cc11';
const SURVEY_ID = '01890070-0000-7000-8000-00000000cc12';

function layer(overrides: Partial<MapLayer> = {}): MapLayer {
  return {
    id: PLAN_ID,
    site_id: '01890000-0000-7000-8000-000000000001',
    name: 'Ground floor',
    kind: 'floor_plan',
    image_url: `/api/v1/grounds/layers/${PLAN_ID}/image`,
    image_width_px: 1600,
    image_height_px: 1200,
    scale_mm_per_px: 12.5,
    calibration: { scale_mm_per_px: 12.5, points: [] },
    ordinal: 0,
    ...overrides,
  };
}

/** A survey with no control points: the state an earlier release exists to get a layer out of. */
const UNCALIBRATED = layer({
  id: SURVEY_ID,
  name: 'Property survey',
  kind: 'survey',
  scale_mm_per_px: null,
  calibration: { scale_mm_per_px: null, points: [] },
  ordinal: 1,
});

function location(overrides: Partial<LocationRef> = {}): LocationRef {
  return {
    id: '01890010-0000-7000-8000-00000000cc21',
    name: 'The south window',
    kind: 'room',
    is_outdoor: false,
    is_covered: false,
    sun_exposure: 'bright_indirect',
    map_layer_id: null,
    specimen_count: 3,
    ...overrides,
  };
}

function specimen(overrides: Partial<SpecimenDetail> = {}): SpecimenDetail {
  return {
    id: SPECIMEN_ID,
    display_name: 'Basil the First',
    nickname: 'Basil the First',
    cultivar: null,
    species: null,
    is_group: false,
    count: 1,
    location: location(),
    map_layer_id: null,
    pin_px: null,
    is_outdoor: false,
    in_container: true,
    container_litres: 2,
    soil_note: null,
    acquired_on: null,
    provenance: null,
    status: 'thriving',
    primary_photo_url: null,
    created_at: null,
    ...overrides,
  };
}

function pin(overrides: Partial<Pin> = {}): Pin {
  return {
    specimen_id: SPECIMEN_ID,
    layer_id: PLAN_ID,
    px: { x: 1200, y: 240 },
    specimen: {
      id: SPECIMEN_ID,
      display_name: 'Basil the First',
      is_outdoor: false,
      thumb_url: null,
    },
    ...overrides,
  };
}

// -------------------------------------------------------------- the states

describe('where a plant is on the map', () => {
  it('gives the place and the distance on a calibrated sheet', () => {
    const where = place(specimen(), [layer()], [pin()]);
    expect(where.state).toBe('pinned');
    expect(where.placed).toBe(true);
    expect(where.layer?.id).toBe(PLAN_ID);
    expect(where.sentence).toContain('Ground floor');
    expect(where.caveat).toBeNull();
  });

  it('never puts pixel coordinates in front of a reader', () => {
    const px = { x: 1337, y: 429 };
    const where = place(specimen(), [layer()], [pin({ px })]);
    expect(where.sentence).not.toContain(String(px.x));
    expect(where.sentence).not.toContain(String(px.y));
  });

  it('gives a place and no distance on a sheet nobody has calibrated', () => {
    const where = place(
      specimen({ is_outdoor: true }),
      [UNCALIBRATED],
      [pin({ layer_id: SURVEY_ID, px: { x: 500, y: 500 } })],
    );
    expect(where.state).toBe('pinned_without_scale');
    expect(where.placed).toBe(true);
    // The limit travels with the sentence, not behind a tooltip.
    // The sentence says there is no distance; the caveat says what to do
    // about it. Neither is behind a tooltip.
    expect(where.sentence).toContain('not calibrated');
    expect(where.caveat).toContain('Calibrating Property survey');
    expect(where.sentence).not.toMatch(/\d+(\.\d+)?\s?(cm|m|km)\b/);
  });

  it('says a plant is listed against a sheet and not yet placed on it', () => {
    const where = place(specimen(), [layer()], [pin({ px: null })]);
    expect(where.state).toBe('awaiting_pin');
    expect(where.placed).toBe(false);
    expect(where.sentence).toContain('not yet placed');
    expect(where.linkPlain).toContain('Ground floor');
  });

  it('distinguishes a place the Register knows from a pin the map holds', () => {
    const where = place(specimen({ location: location({ map_layer_id: PLAN_ID }) }), [layer()], []);
    expect(where.state).toBe('place_has_a_plan');
    expect(where.sentence).toContain('The south window');
    expect(where.sentence).toContain('Ground floor');
    expect(where.sentence).toMatch(/no pin/i);
    expect(where.layer?.id).toBe(PLAN_ID);
  });

  it('says so when its place is recorded and no plan covers that place', () => {
    const where = place(specimen(), [layer()], []);
    expect(where.state).toBe('place_has_no_plan');
    expect(where.sentence).toContain('The south window');
    expect(where.caveat).toMatch(/can still be pinned/i);
  });

  it('says there is nowhere to pin anything when no plan is lodged', () => {
    const where = place(specimen(), [], []);
    expect(where.state).toBe('no_plans');
    expect(where.caveat).toMatch(/upload/i);
  });

  it('admits both absences when neither a place nor a pin is recorded', () => {
    const where = place(specimen({ location: null }), [layer()], []);
    expect(where.state).toBe('unplaced');
    expect(where.sentence).toMatch(/no location is recorded/i);
  });
});

// ----------------------------------------------------- two records, one truth

describe('which record answers for the pin', () => {
  it('prefers the Grounds, because the Grounds is what the map writes', () => {
    const where = place(
      specimen({ map_layer_id: SURVEY_ID, pin_px: { x: 10, y: 10 } }),
      [layer(), UNCALIBRATED],
      [pin()],
    );
    expect(where.layer?.id).toBe(PLAN_ID);
    expect(where.state).toBe('pinned');
  });

  it("falls back to the specimen's own columns when the Grounds holds no pin", () => {
    const where = place(
      specimen({ map_layer_id: PLAN_ID, pin_px: { x: 100, y: 100 } }),
      [layer()],
      [],
    );
    expect(where.state).toBe('pinned');
    expect(where.layer?.id).toBe(PLAN_ID);
  });

  it('never reports a pin on a sheet this deployment does not hold', () => {
    const where = place(
      specimen({ location: null, map_layer_id: 'a-layer-that-is-gone', pin_px: { x: 1, y: 1 } }),
      [layer()],
      [],
    );
    expect(where.placed).toBe(false);
    expect(where.state).toBe('unplaced');
  });
});

// ------------------------------------------------- a failed read is not a no

describe('when the Grounds cannot be read', () => {
  it('does not report an unreadable map as an unpinned plant', () => {
    const where = place(specimen(), null, null, 'The greenhouse answered with an error (502).');
    expect(where.state).toBe('unknown');
    expect(where.sentence).toMatch(/could not be checked/i);
    expect(where.caveat).toContain('502');
  });

  it('keeps the way to the map open even then', () => {
    const where = place(specimen(), null, null);
    expect(where.href).toContain('/grounds?');
    expect(where.href).toContain(SPECIMEN_ID);
  });
});

// ------------------------------------------------------------------- links

describe('the link to the map', () => {
  it('carries the plant, so the map can say where it is on arrival', () => {
    expect(groundsHref(SPECIMEN_ID, null)).toBe(`/grounds?specimen=${SPECIMEN_ID}`);
  });

  it('carries the sheet too, when one is known', () => {
    expect(groundsHref(SPECIMEN_ID, PLAN_ID)).toBe(
      `/grounds?specimen=${SPECIMEN_ID}&layer=${PLAN_ID}`,
    );
  });

  it('is the same round trip the pins make: specimen id in, specimen id out', () => {
    const where = place(specimen(), [layer()], [pin()]);
    expect(where.href).toBe(groundsHref(SPECIMEN_ID, PLAN_ID));
  });
});

// ------------------------------------------------------------- the panel

describe('the panel on the Register entry', () => {
  it('renders the sentence, the caveat and one link', () => {
    const where = place(
      specimen({ is_outdoor: true }),
      [UNCALIBRATED],
      [pin({ layer_id: SURVEY_ID })],
    );
    const markup = html(WhereOnMap as never, { place: where });
    const body = text(markup);
    expect(body).toContain('Property survey');
    expect(body).toContain('Calibrating Property survey');
    // The server render escapes `&` in an href, so the link is compared in the
    // form it actually ships in.
    expect(markup).toContain(`href="${where.href.replace(/&/g, '&amp;')}"`);
  });

  it('pairs the themed name with a plain one, every state', () => {
    const states = [
      place(specimen(), [layer()], [pin()]),
      place(specimen(), [layer()], [pin({ px: null })]),
      place(specimen(), [layer()], []),
      place(specimen(), [], []),
      place(specimen(), null, null, 'No answer'),
    ];
    for (const where of states) {
      const body = text(html(WhereOnMap as never, { place: where }));
      expect(body).toContain('Where it is on the map');
      expect(where.linkPlain.trim().length).toBeGreaterThan(0);
    }
  });

  it('shows a failed read as a stale notice, not as an answer', () => {
    const markup = html(WhereOnMap as never, {
      place: place(specimen(), null, null, 'The greenhouse refused the request (503).'),
    });
    expect(text(markup)).toContain('503');
  });
});
