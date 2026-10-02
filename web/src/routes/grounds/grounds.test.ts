/** The Grounds route's own suite.
 *
 * The map itself is the maps module's and is tested in `web/src/lib/map/`. What is tested
 * here is only what the route decides: which sheet a link opens, and what the
 * page says to somebody a Specimen page sent here to look at one plant.
 *
 * Layers and pins are built locally rather than read out of `fixtures/`
 *: these are assertions about the route's arithmetic, and a copy of
 * The test suite's data in them would be a second copy going stale.
 */

import { describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import type { MapLayer, Pin } from '$map';
import GroundsPage from './+page.svelte';
import { arrival, orderLayers, specimenBackHref } from './arrival';
import { NOT_IN_KEEPING, placeable, unpinnedCount, type RegisterEntry } from './roster';

const PLAN_ID = '01890070-0000-7000-8000-00000000aaa1';
const SURVEY_ID = '01890070-0000-7000-8000-00000000aaa2';
const SPECIMEN_ID = '01890040-0000-7000-8000-00000000bbb1';

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

const UNCALIBRATED = layer({
  id: SURVEY_ID,
  name: 'Property survey',
  kind: 'survey',
  scale_mm_per_px: null,
  calibration: { scale_mm_per_px: null, points: [] },
  ordinal: 1,
});

function pin(overrides: Partial<Pin> = {}): Pin {
  return {
    specimen_id: SPECIMEN_ID,
    layer_id: PLAN_ID,
    px: { x: 1200, y: 300 },
    specimen: {
      id: SPECIMEN_ID,
      display_name: 'Basil the First',
      is_outdoor: false,
      thumb_url: null,
    },
    ...overrides,
  };
}

function entry(overrides: Partial<RegisterEntry> = {}): RegisterEntry {
  return {
    id: SPECIMEN_ID,
    display_name: 'Basil the First',
    is_outdoor: false,
    status: 'thriving',
    ...overrides,
  };
}

// ------------------------------------------------------------ which sheet

describe('which sheet a link opens', () => {
  it('leaves the API order alone when no sheet was asked for', () => {
    const layers = [layer(), UNCALIBRATED];
    expect(orderLayers(layers, null).map((l) => l.id)).toEqual([PLAN_ID, SURVEY_ID]);
  });

  it('puts the asked-for sheet first, because the map opens the first one', () => {
    const layers = [layer(), UNCALIBRATED];
    expect(orderLayers(layers, SURVEY_ID).map((l) => l.id)).toEqual([SURVEY_ID, PLAN_ID]);
  });

  it('keeps every sheet in the switcher, so nothing is hidden by the ordering', () => {
    const layers = [layer(), UNCALIBRATED];
    expect(orderLayers(layers, SURVEY_ID)).toHaveLength(layers.length);
  });

  it('falls back to the API order for a sheet this deployment does not hold', () => {
    const layers = [layer(), UNCALIBRATED];
    expect(orderLayers(layers, 'no-such-layer').map((l) => l.id)).toEqual([PLAN_ID, SURVEY_ID]);
  });
});

// --------------------------------------------------------------- arrival

describe('arriving from a Specimen page', () => {
  it('says nothing at all when no plant sent us here', () => {
    expect(arrival(null, [layer()], [pin()])).toBeNull();
  });

  it('names the plant, where it is, and the way back', () => {
    const came = arrival(SPECIMEN_ID, [layer()], [pin()]);
    expect(came?.placed).toBe(true);
    expect(came?.layerId).toBe(PLAN_ID);
    expect(came?.name).toBe('Basil the First');
    expect(came?.backHref).toBe(specimenBackHref(SPECIMEN_ID));
    expect(came?.sentence).toContain('Basil the First is here');
    expect(came?.sentence).toContain('Ground floor');
  });

  it('never leaks pixel coordinates into the sentence', () => {
    const px = { x: 1234, y: 567 };
    const came = arrival(SPECIMEN_ID, [layer()], [pin({ px })]);
    expect(came?.sentence).not.toContain(String(px.x));
    expect(came?.sentence).not.toContain(String(px.y));
  });

  it('gives no distance on a sheet with no scale, and does not invent one', () => {
    const came = arrival(
      SPECIMEN_ID,
      [UNCALIBRATED],
      [pin({ layer_id: SURVEY_ID, px: { x: 400, y: 400 } })],
    );
    expect(came?.placed).toBe(true);
    expect(came?.sentence).toContain('not calibrated');
    expect(came?.sentence).not.toMatch(/\d+(\.\d+)?\s?(m|cm|km)\b/);
  });

  it('says plainly that a plant in the Register has no pin yet', () => {
    const came = arrival(SPECIMEN_ID, [layer()], [pin({ px: null })]);
    expect(came?.placed).toBe(false);
    expect(came?.layerId).toBe(PLAN_ID);
    expect(came?.sentence).toContain('not placed on Ground floor yet');
  });

  it('admits it when neither the map nor the Register knows the plant', () => {
    const came = arrival(SPECIMEN_ID, [layer()], []);
    expect(came?.placed).toBe(false);
    expect(came?.layerId).toBeNull();
    expect(came?.sentence).toMatch(/neither the map nor the Register/i);
    // Still a way back: the link that got here may be the only handle on it.
    expect(came?.backHref).toBe(specimenBackHref(SPECIMEN_ID));
  });

  it('does not claim a plant is gone when the Register was never read', () => {
    const came = arrival(SPECIMEN_ID, [layer()], [], false);
    expect(came?.sentence).toMatch(/Register could not be read/i);
    expect(came?.sentence).not.toMatch(/removed/i);
  });

  it('admits it when the pin names a sheet that is gone', () => {
    const came = arrival(SPECIMEN_ID, [UNCALIBRATED], [pin({ layer_id: 'lost-layer' })]);
    expect(came?.placed).toBe(false);
    expect(came?.sentence).toMatch(/no longer holds/i);
  });
});

// -------------------------------------------- every specimen can be pinned

describe('the plants no sheet holds a pin for', () => {
  const OTHER = '01890040-0000-7000-8000-00000000bbb2';

  it('offers a placeable row on every sheet, so a first pin can be placed', () => {
    const layers = [layer(), UNCALIBRATED];
    const rows = placeable(layers, [], [entry()]);
    expect(rows).toHaveLength(layers.length);
    expect(rows.every((row) => row.px === null)).toBe(true);
    expect(new Set(rows.map((row) => row.layer_id))).toEqual(new Set(layers.map((l) => l.id)));
  });

  it('carries the plant’s own name, never a placeholder', () => {
    const [row] = placeable([layer()], [], [entry({ display_name: 'Mother-in-law’s tongue' })]);
    expect(row.specimen?.display_name).toBe('Mother-in-law’s tongue');
  });

  it('leaves a pinned plant alone — one row, the real one', () => {
    const rows = placeable([layer()], [pin()], [entry()]);
    expect(rows).toHaveLength(1);
    expect(rows[0].px).not.toBeNull();
  });

  it('puts a lifted pin back in reach, because lifting deletes the row', () => {
    // `PUT /grounds/pins` with a null px removes the pin outright, so the plant
    // vanishes from `GET /grounds/pins` and could never be placed again.
    const rows = placeable([layer()], [], [entry()]);
    expect(rows.some((row) => row.specimen_id === SPECIMEN_ID && row.px === null)).toBe(true);
  });

  it.each([...NOT_IN_KEEPING])('does not offer a sheet to a %s plant', (status) => {
    expect(placeable([layer()], [], [entry({ status })])).toHaveLength(0);
  });

  it('keeps the pin of a plant set aside, which is the Register’s business', () => {
    // a plant set aside is still named. Its pin is data, not an offer.
    const rows = placeable([layer()], [pin()], [entry({ status: 'archived' })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].px).not.toBeNull();
  });

  it('guesses nothing when the Register could not be read', () => {
    const rows = placeable([layer()], [pin()], null);
    expect(rows).toEqual([pin()]);
  });

  it('counts the plants still waiting for a pin', () => {
    const register = [entry(), entry({ id: OTHER, display_name: 'The Sentinel' })];
    expect(unpinnedCount([pin()], register)).toBe(1);
    expect(unpinnedCount([], register)).toBe(2);
    expect(unpinnedCount([pin({ px: null })], register)).toBe(2);
    expect(unpinnedCount([], null)).toBe(0);
  });
});

// ------------------------------------------------------- the page itself

const ok = <T>(value: T) => ({ value, error: null });
const failed = (error: string) => ({ value: null, error });

function pageData(overrides: Record<string, unknown> = {}) {
  return {
    layers: ok([layer()]),
    pins: ok([pin()]),
    zones: ok([]),
    register: ok({ entries: [entry()], truncated: false }),
    wantedLayerId: null,
    fromSpecimenId: null,
    ...overrides,
  };
}

describe('the Grounds page', () => {
  it('holds the map back rather than drawing a sheet with no pins on it', () => {
    const markup = html(GroundsPage as never, {
      data: pageData({ pins: failed('The pins broke') }),
    });
    expect(text(markup)).toContain('The pins broke');
    expect(markup).not.toContain('role="application"');
  });

  it('says the plans cannot be fetched instead of showing an empty Grounds', () => {
    const markup = html(GroundsPage as never, {
      data: pageData({ layers: failed('No answer from the greenhouse') }),
    });
    expect(text(markup)).toContain('No answer from the greenhouse');
  });

  it('draws the map, and the pin anchor the exit criterion runs through', () => {
    const markup = html(GroundsPage as never, { data: pageData() });
    expect(markup).toContain(`href="/specimen/${SPECIMEN_ID}/register"`);
    // Asserted here so the "held back" test above is not vacuous: this is the
    // marker the map renders and the failed-pins page must not.
    expect(markup).toContain('role="application"');
  });

  it('greets an arrival from a Specimen page with a way back', () => {
    const markup = html(GroundsPage as never, {
      data: pageData({ fromSpecimenId: SPECIMEN_ID }),
    });
    const body = text(markup);
    expect(body).toContain('Basil the First is here');
    expect(markup).toContain(`href="${specimenBackHref(SPECIMEN_ID)}"`);
  });

  it('loses the zones and keeps the map when only the zones fail', () => {
    const markup = html(GroundsPage as never, {
      data: pageData({ zones: failed('No locations') }),
    });
    expect(text(markup)).toContain('No locations');
    expect(markup).toContain(`href="/specimen/${SPECIMEN_ID}/register"`);
  });
});
