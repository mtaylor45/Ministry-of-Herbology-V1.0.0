/** The rows the map and the list are both drawn from.
 *
 * The accessibility claim this parts of the project makes is that the list is the
 * *equivalent* of the map, not a summary of it. That claim is only true if
 * both are rendered from one array, so these tests are about that array:
 * every pin is in it, every row can be opened, and an unplaced plant is in it
 * too rather than quietly dropped.
 */

import { describe, expect, it } from 'vitest';
import {
  displayName,
  layerSummary,
  pinRows,
  positionSentence,
  quadrantOf,
  specimenHref,
  unplaced,
} from './pins';
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

function pin(over: Partial<Pin> = {}): Pin {
  return {
    specimen_id: 'sp-1',
    layer_id: 'plan',
    px: { x: 100, y: 100 },
    specimen: { id: 'sp-1', display_name: 'Gilderoy', is_outdoor: false, thumb_url: null },
    ...over,
  };
}

describe('specimenHref', () => {
  it('is the earlier exit criterion, in one function', () => {
    // "every specimen can be pinned, and tapping a pin opens its Specimen
    // page". The map marker and the list row both use this.
    expect(specimenHref('abc')).toBe('/specimen/abc/register');
  });
});

describe('quadrantOf', () => {
  it.each([
    [{ x: 10, y: 10 }, 'upper left'],
    [{ x: 450, y: 10 }, 'upper centre'],
    [{ x: 880, y: 10 }, 'upper right'],
    [{ x: 10, y: 580 }, 'lower left'],
    [{ x: 880, y: 580 }, 'lower right'],
  ])('reads %o as %s', (px, expected) => {
    expect(quadrantOf(layer(), px)).toBe(expected);
  });

  it('calls the middle the middle rather than "middle centre"', () => {
    expect(quadrantOf(layer(), { x: 450, y: 300 })).toBe('the middle');
  });

  it('does not divide by a zero-sized sheet', () => {
    expect(quadrantOf(layer({ image_width_px: 0, image_height_px: 0 }), { x: 0, y: 0 })).toBe(
      'the middle',
    );
  });
});

describe('positionSentence', () => {
  it('says where, and admits when there is no distance to give', () => {
    const sentence = positionSentence(layer(), { x: 10, y: 10 });
    expect(sentence).toContain('upper left of Ground floor');
    expect(sentence).toContain('not calibrated');
    // Never a raw pixel pair: "at 10, 10" tells a listener nothing.
    expect(sentence).not.toMatch(/\b10,\s*10\b/);
  });

  it('gives distances once the layer is calibrated', () => {
    const calibrated = layer({ scale_mm_per_px: 10 });
    const sentence = positionSentence(calibrated, { x: 1000, y: 2000 });
    expect(sentence).toContain('10 m in from the left edge');
    expect(sentence).toContain('20 m down from the top');
  });

  it('says plainly that an unplaced plant is unplaced', () => {
    expect(positionSentence(layer(), null)).toBe('Not yet placed on Ground floor');
  });
});

describe('pinRows', () => {
  it('carries every pin on the layer and nothing from another', () => {
    const rows = pinRows(layer(), [
      pin({ specimen_id: 'a' }),
      pin({ specimen_id: 'b' }),
      pin({ specimen_id: 'c', layer_id: 'survey' }),
    ]);
    expect(rows.map((row) => row.specimenId)).toEqual(['a', 'b']);
  });

  it('sorts by name, so the reading order is predictable', () => {
    const rows = pinRows(layer(), [
      pin({ specimen_id: 'z', specimen: { ...pin().specimen!, display_name: 'Zinnia' } }),
      pin({ specimen_id: 'a', specimen: { ...pin().specimen!, display_name: 'Aloe' } }),
    ]);
    expect(rows.map((row) => row.name)).toEqual(['Aloe', 'Zinnia']);
  });

  it('numbers each row in the order it is read', () => {
    const rows = pinRows(layer(), [pin({ specimen_id: 'a' }), pin({ specimen_id: 'b' })]);
    expect(rows.map((row) => `${row.ordinal} of ${row.total}`)).toEqual(['1 of 2', '2 of 2']);
  });

  it('puts the placed pins first, so the numbering matches the reading order', () => {
    const rows = pinRows(layer(), [
      pin({ specimen_id: 'a', px: null, specimen: { ...pin().specimen!, display_name: 'Aloe' } }),
      pin({ specimen_id: 'z', specimen: { ...pin().specimen!, display_name: 'Zinnia' } }),
    ]);
    expect(rows.map((row) => row.name)).toEqual(['Zinnia', 'Aloe']);
    expect(rows[0].ordinal).toBe(1);
  });

  it('does not number an unplaced plant, because it is not one of a set', () => {
    const rows = pinRows(layer(), [pin({ specimen_id: 'a' }), pin({ specimen_id: 'b', px: null })]);
    expect(rows[0].total).toBe(1);
    expect(rows[1].ordinal).toBe(0);
  });

  it('gives every row a label that names the plant and says where it is', () => {
    const [row] = pinRows(layer({ scale_mm_per_px: 10 }), [pin({ px: { x: 10, y: 10 } })]);
    expect(row.label).toContain('Gilderoy');
    expect(row.label).toContain('upper left');
    expect(row.href).toBe('/specimen/sp-1/register');
  });

  it('keeps an unplaced pin in the list rather than dropping it', () => {
    const rows = pinRows(layer(), [pin({ px: null })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].placed).toBe(false);
    expect(rows[0].href).toBe('/specimen/sp-1/register');
  });

  it('survives a pin whose specimen brief never arrived', () => {
    const rows = pinRows(layer(), [pin({ specimen: null })]);
    expect(rows[0].name).toBe('Unnamed specimen');
  });
});

describe('displayName', () => {
  it('falls back rather than rendering an empty label', () => {
    expect(displayName(pin({ specimen: { ...pin().specimen!, display_name: '  ' } }))).toBe(
      'Unnamed specimen',
    );
  });
});

describe('unplaced', () => {
  it('lists the plants in the Register that no pin covers', () => {
    const register = [
      { id: 'a', display_name: 'Aloe' },
      { id: 'b', display_name: 'Basil' },
    ];
    expect(unplaced(register, [pin({ specimen_id: 'a' })])).toEqual([{ id: 'b', name: 'Basil' }]);
  });

  it('counts a lifted pin as unplaced, because it is', () => {
    const register = [{ id: 'a', display_name: 'Aloe' }];
    expect(unplaced(register, [pin({ specimen_id: 'a', px: null })])).toEqual([
      { id: 'a', name: 'Aloe' },
    ]);
  });
});

describe('layerSummary', () => {
  it('counts only the placed pins, and says where the list is', () => {
    const rows = pinRows(layer(), [pin({ specimen_id: 'a' }), pin({ specimen_id: 'b', px: null })]);
    const summary = layerSummary(layer(), rows);
    expect(summary).toContain('1 plant placed');
    expect(summary).toContain('list below');
  });
});
