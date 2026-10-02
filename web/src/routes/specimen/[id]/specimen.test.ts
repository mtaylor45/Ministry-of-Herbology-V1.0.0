/** The Specimen page's own suite.
 *
 * Rendered through `svelte/server`, the way the design system's library is tested,
 * so the facets are checked without adding a DOM emulator to a `package.json`
 * this parts of the project does not own.
 */

import { describe, expect, it, vi } from 'vitest';
import { count, html, text } from '$ui/render';
import CareValueList from './CareValueList.svelte';
import FactList from './FactList.svelte';
import SeeAlso from './SeeAlso.svelte';
import {
  ApiError,
  reason,
  saveCareValue,
  settle,
  type CareValue,
  type SourceRef,
  type SpecimenDetail,
} from './api';
import {
  CARE_FIELDS,
  careField,
  confidenceStatus,
  displayUnit,
  editTarget,
  formatValue,
  humanise,
  isUncited,
  sentenceName,
  sortCareValues,
  sourceKind,
} from './care';
import { FACETS, facet, facetPath, seeAlso, type FacetId } from './facets';
import GrowthLog from './journal/GrowthLog.svelte';
import {
  FIRST_PHOTO,
  growthLogSentence,
  leafFor,
  oldestFirst,
  photoAlt,
  type Photo,
  type Plate,
} from './journal/journalFacet';
import { enrichmentProgress, formatDate, specimenStatus } from './labels';

const SPECIMEN_ID = '01890040-0000-7000-8000-000000000001';
const SPECIES_ID = '01890030-0000-7000-8000-000000000001';

const SOURCE: SourceRef = {
  id: '01890020-0000-7000-8000-000000000006',
  kind: 'perenual',
  title: 'Perenual plant care API',
  url: 'https://perenual.com/docs/api',
  license: 'Perenual terms',
  retrieved_at: '2026-09-15T12:00:00Z',
};

/** A plant as the layout serves it, matched to a species or not. */
function specimenOf(species: { id: string } | null): SpecimenDetail {
  return {
    id: SPECIMEN_ID,
    display_name: 'Basil the First',
    nickname: null,
    cultivar: null,
    species: species
      ? { ...species, accepted_name: 'Ocimum basilicum', common_name: 'basil', family: null }
      : null,
    is_group: false,
    count: 1,
    location: null,
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
  };
}

function careValue(overrides: Partial<CareValue> = {}): CareValue {
  return {
    field: 'water_k_c',
    value: 0.6,
    unit: null,
    source: SOURCE,
    confidence: 'medium',
    is_user_override: false,
    note: null,
    ...overrides,
  };
}

// --------------------------------------------------------------- cross-links

describe('the facets and their cross-links', () => {
  it('names all four facets, journal included', () => {
    expect(FACETS.map((f) => f.id)).toEqual(['register', 'tending', 'compendium', 'journal']);
  });

  it('says the journal is built, and what is on it', () => {
    expect(facet('journal').built).toBe(true);
    expect(facet('journal').blurb).not.toMatch(/not built/i);
    expect(facet('journal').blurb).toMatch(/plate/i);
    expect(facet('journal').blurb).toMatch(/field notes/i);
    expect(facet('journal').blurb).toMatch(/photograph/i);
  });

  it('has no facet left that leads nowhere', () => {
    expect(FACETS.every((f) => f.built)).toBe(true);
  });

  it.each(['register', 'tending', 'compendium', 'journal'] as FacetId[])(
    'links %s to the other three and never to itself',
    (current) => {
      const links = seeAlso(current, SPECIMEN_ID);
      expect(links).toHaveLength(3);
      expect(links.map((l) => l.id)).not.toContain(current);
      expect(new Set(links.map((l) => l.id)).size).toBe(3);
    },
  );

  it('builds facet paths the plan fixes', () => {
    expect(facetPath(SPECIMEN_ID, 'tending')).toBe(`/specimen/${SPECIMEN_ID}/tending`);
    expect(seeAlso('register', SPECIMEN_ID).map((l) => l.href)).toEqual([
      `/specimen/${SPECIMEN_ID}/tending`,
      `/specimen/${SPECIMEN_ID}/compendium`,
      `/specimen/${SPECIMEN_ID}/journal`,
    ]);
  });

  it('pairs every facet name with a plain one', () => {
    for (const f of FACETS) {
      expect(f.plain.trim()).not.toBe('');
      expect(f.themed.trim()).not.toBe('');
      expect(f.plain).not.toBe(f.themed);
    }
  });

  it('renders every see-also link, journal included, and none leads nowhere', () => {
    const markup = html(SeeAlso, { current: 'register', specimenId: SPECIMEN_ID });
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/tending`);
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/compendium`);
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/journal`);
    expect(markup).not.toContain(`/specimen/${SPECIMEN_ID}/register`);
    // Said from an earlier release to an earlier release, and pinned here so it cannot come back
    // for the journal without the test saying so.
    expect(text(markup)).not.toMatch(/leads nowhere/i);
    expect(text(markup)).toContain(facet('journal').blurb);
  });

  it('links the journal facet back to the other three', () => {
    const markup = html(SeeAlso, { current: 'journal', specimenId: SPECIMEN_ID });
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/register`);
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/tending`);
    expect(markup).toContain(`/specimen/${SPECIMEN_ID}/compendium`);
    expect(markup).not.toContain(`/specimen/${SPECIMEN_ID}/journal`);
  });
});

// ------------------------------------------------------------ the journal

describe('the journal facet', () => {
  function photo(overrides: Partial<Photo> = {}): Photo {
    return {
      id: '01890050-0000-7000-8000-000000000001',
      url: `/api/v1/specimens/${SPECIMEN_ID}/photos/01890050-0000-7000-8000-000000000001`,
      thumb_url: null,
      taken_at: '2026-04-02T09:30:00Z',
      caption: null,
      is_primary: false,
      ...overrides,
    };
  }

  const EARLIER = photo({
    id: '01890050-0000-7000-8000-000000000002',
    taken_at: '2026-03-01T08:00:00Z',
    caption: 'Just potted on, two true leaves',
  });
  const LATER = photo({
    id: '01890050-0000-7000-8000-000000000003',
    taken_at: '2026-05-20T18:15:00Z',
    thumb_url: '/thumbs/later.jpg',
    is_primary: true,
  });

  it('reads the growth log forward: oldest first, whatever order the API served', () => {
    // The contract serves newest first. A growth log is read the other way.
    expect(oldestFirst([LATER, EARLIER]).map((p) => p.id)).toEqual([EARLIER.id, LATER.id]);
    expect(oldestFirst([EARLIER, LATER]).map((p) => p.id)).toEqual([EARLIER.id, LATER.id]);
  });

  it('does not reorder its input in place', () => {
    const served = [LATER, EARLIER];
    oldestFirst(served);
    expect(served.map((p) => p.id)).toEqual([LATER.id, EARLIER.id]);
  });

  it('sends a photograph with an unreadable date to the end rather than the middle', () => {
    const undated = photo({ id: 'undated', taken_at: 'not a date' });
    expect(oldestFirst([LATER, undated, EARLIER]).map((p) => p.id)).toEqual([
      EARLIER.id,
      LATER.id,
      'undated',
    ]);
  });

  it('gives every photograph real alt text, never an empty one', () => {
    expect(photoAlt(EARLIER, 'Basil the First', '1 March 2026')).toBe(
      'Just potted on, two true leaves',
    );
    expect(photoAlt(LATER, 'Basil the First', '20 May 2026')).toBe(
      'Photograph of Basil the First, taken 20 May 2026',
    );
    expect(photoAlt(photo({ caption: '   ' }), 'Basil the First', 'today')).toContain('Basil');
  });

  it('counts the log honestly, in a sentence', () => {
    expect(growthLogSentence(0, '', '')).toMatch(/no photographs/i);
    expect(growthLogSentence(1, '1 March 2026', '1 March 2026')).toBe(
      'One photograph, taken 1 March 2026.',
    );
    expect(growthLogSentence(2, '1 March 2026', '20 May 2026')).toBe(
      '2 photographs, oldest first, from 1 March 2026 to 20 May 2026.',
    );
  });

  it('renders two contract-shaped photographs, in order, with dates and alt text', () => {
    // The day C lands `POST /specimens/{id}/photos`, this is what the GET will
    // feed the log. Nothing here changes on that day.
    const markup = html(GrowthLog, {
      photos: [LATER, EARLIER],
      specimenName: 'Basil the First',
    });
    expect(count(markup, 'img')).toBe(2);
    expect(count(markup, 'time')).toBe(2);
    expect(markup.indexOf(EARLIER.taken_at)).toBeLessThan(markup.indexOf(LATER.taken_at));
    expect(markup).toContain('src="/thumbs/later.jpg"');
    expect(markup).toContain('alt="Just potted on, two true leaves"');
    expect(markup).toContain('datetime="2026-03-01T08:00:00Z"');
    const body = text(markup);
    expect(body).toContain('Photo growth log, oldest first');
    expect(body).toMatch(/2 photographs, oldest first/);
    expect(body).toContain('The Register');
    expect(body).toContain('No caption');
  });

  it('without a specimen id it is read-only and says nothing about adding', () => {
    const markup = html(GrowthLog, { photos: [EARLIER], specimenName: 'Basil the First' });
    expect(markup).not.toMatch(/<input[^>]+type="file"/);
    expect(text(html(GrowthLog, { photos: [], specimenName: 'Basil the First' }))).toContain(
      'No photographs yet',
    );
  });

  it('with a specimen id it offers the upload control, PNG or JPEG, and who took it', () => {
    const markup = html(GrowthLog, {
      photos: [],
      specimenName: 'Basil the First',
      specimenId: 'p1',
      members: [{ id: 'm1', name: 'Keeper', role: 'keeper' }],
    });
    expect(markup).toMatch(/<input[^>]+type="file"/);
    expect(markup).toContain('accept="image/png,image/jpeg"');
    const body = text(markup);
    expect(body).toContain(FIRST_PHOTO);
    expect(body).toContain('Who took it');
    expect(body).not.toContain('cannot be added from here yet');
  });

  it('shows a failed read as a stale notice, not as an empty log', () => {
    const body = text(
      html(GrowthLog, {
        photos: [],
        specimenName: 'Basil the First',
        error: 'The greenhouse answered with an error (502).',
      }),
    );
    expect(body).toContain('502');
    expect(body).not.toContain('No photographs yet');
  });

  it("finds this plant's leaf by the rule the book uses, and never borrows a plate", () => {
    const plate: Plate = {
      id: '01890060-0000-7000-8000-000000000001',
      species_id: SPECIES_ID,
      specimen_id: null,
      image_url: '/api/v1/journal/plates/01890060-0000-7000-8000-000000000001/image',
      thumb_url: null,
      origin: 'generated',
      license: null,
      attribution: null,
      approved: false,
    };
    const matched = leafFor(specimenOf({ id: SPECIES_ID }), [plate]);
    expect(matched.state).toBe('waiting');
    expect(matched.plate?.id).toBe(plate.id);
    expect(matched.botanicalName).toBe('Ocimum basilicum');

    const other = leafFor(specimenOf({ id: '01890030-0000-7000-8000-000000000099' }), [plate]);
    expect(other.state).toBe('absent');
    expect(other.plate).toBeNull();

    const unmatched = leafFor(specimenOf(null), [plate]);
    expect(unmatched.state).toBe('absent');
  });
});

// ---------------------------------------------------- citations & confidence

describe('confidence, as the design requires it shown', () => {
  it('reads an uncited value as unknown rather than leaving it blank', () => {
    const status = confidenceStatus('unknown');
    expect(status.plain).toMatch(/unknown/i);
    expect(status.tone).toBe('ailing');
    expect(status.themed).not.toBe(status.plain);
  });

  it.each(['high', 'medium', 'low', 'unknown'] as const)(
    'pairs the themed word for %s confidence with a plain one',
    (confidence) => {
      const status = confidenceStatus(confidence);
      expect(status.plain.trim()).not.toBe('');
      expect(status.themed.trim()).not.toBe('');
    },
  );

  it('lets a user correction outrank whatever the sources said', () => {
    expect(confidenceStatus('unknown', true).plain).toMatch(/your correction/i);
    expect(confidenceStatus('unknown', true).tone).toBe('thriving');
  });

  it('counts a value as uncited when it has no source or unknown confidence', () => {
    expect(isUncited(careValue({ confidence: 'unknown', source: null }))).toBe(true);
    expect(isUncited(careValue({ confidence: 'unknown' }))).toBe(true);
    expect(isUncited(careValue({ source: null }))).toBe(true);
    expect(isUncited(careValue())).toBe(false);
    expect(
      isUncited(careValue({ confidence: 'unknown', source: null, is_user_override: true })),
    ).toBe(false);
  });
});

describe('reading a care value', () => {
  it('never shows a raw null', () => {
    expect(formatValue(null, 'water_k_c')).toBe('Not recorded');
    expect(formatValue(undefined, 'water_k_c')).toBe('Not recorded');
    expect(formatValue('', 'soil_type')).toBe('Not recorded');
  });

  it('says yes and no rather than true and false', () => {
    expect(formatValue(true, 'toxic_to_pets')).toBe('Yes');
    expect(formatValue(false, 'toxic_to_pets')).toBe('No');
  });

  it('spells light labels out', () => {
    expect(formatValue('bright_indirect', 'light_label')).toBe('Bright, indirect light');
    expect(formatValue('some_new_label', 'light_label')).toBe('Some new label');
  });

  it('carries the unit, with the symbol the rest of the app uses', () => {
    expect(formatValue(10, 'min_temp_c', 'C')).toBe('10 °C');
    expect(formatValue(9, 'water_interval_days', 'days')).toBe('9 days');
    expect(displayUnit('C')).toBe('°C');
    expect(displayUnit('pct')).toBe('%');
    expect(displayUnit(null)).toBeUndefined();
    expect(displayUnit('mm')).toBe('mm');
  });

  it('keeps long decimals from swamping a phone screen', () => {
    expect(formatValue(0.123456, 'water_k_c')).toBe('0.12');
    expect(formatValue(3, 'water_k_c')).toBe('3');
  });

  it('gives a field the contract grows a readable name rather than a column name', () => {
    expect(humanise('water_k_c')).toBe('Water k c');
    expect(careField('brand_new_field').plain).toBe('Brand new field');
    expect(careField('water_k_c').plain).toBe('Water need');
  });

  it('keeps pH capitalised mid-sentence', () => {
    expect(sentenceName('soil_ph_min')).toBe('lowest soil pH');
    expect(sentenceName('water_k_c')).toBe('water need');
  });

  it('reads the watering fields before the rest', () => {
    const sorted = sortCareValues([
      careValue({ field: 'toxic_to_pets' }),
      careValue({ field: 'light_label' }),
      careValue({ field: 'water_k_c' }),
      careValue({ field: 'min_temp_c' }),
    ]);
    expect(sorted.map((v) => v.field)).toEqual([
      'water_k_c',
      'min_temp_c',
      'light_label',
      'toxic_to_pets',
    ]);
  });

  it('names a source in words rather than by its slug', () => {
    expect(sourceKind('powo')).toBe('Plants of the World Online');
    expect(sourceKind('something_else')).toBe('Something else');
  });
});

describe('where an edit goes', () => {
  it('corrects this plant alone where the contract has an override field', () => {
    const target = editTarget('water_k_c', SPECIMEN_ID, SPECIES_ID);
    expect(target).toMatchObject({
      route: 'specimen',
      id: SPECIMEN_ID,
      overrideField: 'water_k_c_override',
    });
    expect(target?.scope).toMatch(/this plant only/i);
  });

  it.each(['water_k_c', 'water_interval_days', 'min_temp_c'])(
    '%s has a specimen override in the contract',
    (field) => {
      expect(CARE_FIELDS[field].overrideField).toMatch(/_override$/);
    },
  );

  it('falls back to the species for fields the contract records there', () => {
    expect(editTarget('light_label', SPECIMEN_ID, SPECIES_ID)).toMatchObject({
      route: 'species',
      id: SPECIES_ID,
      field: 'light_label',
    });
  });

  it('has nowhere to put a species-level edit for an unidentified plant', () => {
    expect(editTarget('light_label', SPECIMEN_ID, null)).toBeNull();
    // A specimen override still works: it does not need a species.
    expect(editTarget('water_k_c', SPECIMEN_ID, null)).not.toBeNull();
  });
});

// ------------------------------------------------------------- the care list

describe('the care value list', () => {
  const values = [
    careValue(),
    careValue({ field: 'min_temp_c', value: 10, unit: 'C', confidence: 'high' }),
    careValue({
      field: 'light_label',
      value: 'bright_indirect',
      source: null,
      confidence: 'unknown',
    }),
  ];

  const markup = html(CareValueList, {
    values,
    specimenId: SPECIMEN_ID,
    speciesId: SPECIES_ID,
  });

  it('shows a source beside every value that has one', () => {
    expect(text(markup)).toContain('Perenual plant care API');
    expect(markup).toContain('https://perenual.com/docs/api');
  });

  it('says outright when a value has no source, rather than hiding it', () => {
    expect(text(markup)).toMatch(/Source: none\. Nothing was consulted for this figure\./);
  });

  it('warns above the list when anything is uncited', () => {
    expect(text(markup)).toMatch(/No source for one value/);
    expect(text(markup)).toMatch(/no soil sensor/i);
  });

  it('raises no warning when every value is attested', () => {
    const clean = html(CareValueList, {
      values: [careValue()],
      specimenId: SPECIMEN_ID,
      speciesId: SPECIES_ID,
    });
    expect(text(clean)).not.toMatch(/No source for/);
  });

  it('offers a correction for every value, uncited ones included', () => {
    expect(markup.match(/Correct /g)?.length).toBeGreaterThanOrEqual(values.length);
    expect(text(markup)).toContain('Correct water need');
    expect(text(markup)).toContain('Correct light');
  });

  it('shows the confidence next to each value, in words', () => {
    const shown = text(markup);
    expect(shown).toContain('Medium confidence');
    expect(shown).toContain('High confidence');
    expect(shown).toContain('Unknown — no source for this');
  });

  it('shows the unit with its symbol', () => {
    expect(text(markup)).toContain('10 °C');
  });
});

describe('the fact list', () => {
  it('renders each term with its value and never an empty cell', () => {
    const markup = html(FactList, {
      facts: [
        { plain: 'Location', themed: 'Where it stands', value: 'Study' },
        { plain: 'Soil', value: 'Not recorded', note: 'Nobody wrote it down.' },
      ],
    });
    const shown = text(markup);
    expect(shown).toContain('Location');
    expect(shown).toContain('Where it stands');
    expect(shown).toContain('Study');
    expect(shown).toContain('Not recorded');
    expect(shown).toContain('Nobody wrote it down.');
  });
});

// ------------------------------------------------------- status & enrichment

describe('the Register status vocabulary', () => {
  it.each([
    'thriving',
    'struggling',
    'dormant',
    'overwintering',
    'lost',
    'given_away',
    'archived',
  ] as const)('pairs %s with a plain meaning', (status) => {
    const pair = specimenStatus(status);
    expect(pair.plain.trim()).not.toBe('');
    expect(pair.themed.trim()).not.toBe('');
    expect(pair.plain).not.toBe(pair.themed);
  });

  it('does not invent a meaning for a status it has never seen', () => {
    expect(specimenStatus('sprouting_teeth').plain).toMatch(/not one the app knows/);
  });
});

describe('the enrichment progress state', () => {
  it('admits it is still working rather than showing a finished spinner', () => {
    for (const state of ['pending', 'running'] as const) {
      const progress = enrichmentProgress(state, true);
      expect(progress.busy).toBe(true);
      expect(progress.plain).toMatch(/looking|reading/i);
    }
  });

  it('stops claiming to be busy once the queue is done', () => {
    expect(enrichmentProgress('complete', true).busy).toBe(false);
  });

  it('says a failed lookup failed, and that nothing was invented', () => {
    const progress = enrichmentProgress('failed', true);
    expect(progress.busy).toBe(false);
    expect(progress.plain).toMatch(/failed/i);
    expect(progress.plain).toMatch(/nothing was invented/i);
  });

  it('tells an unidentified plant apart from a finished lookup', () => {
    const progress = enrichmentProgress(null, false);
    expect(progress.state).toBe('unidentified');
    expect(progress.busy).toBe(false);
  });

  it('pairs every progress state with a plain sentence', () => {
    for (const state of ['pending', 'running', 'complete', 'failed'] as const) {
      const progress = enrichmentProgress(state, true);
      expect(progress.themed.trim()).not.toBe('');
      expect(progress.plain.trim()).not.toBe('');
    }
  });
});

describe('dates', () => {
  it('says so rather than showing "Invalid Date"', () => {
    expect(formatDate(null)).toBe('Not recorded');
    expect(formatDate('not a date')).toBe('Not recorded');
    expect(formatDate(undefined, 'at an unrecorded time')).toBe('at an unrecorded time');
  });

  it('formats a real timestamp', () => {
    expect(formatDate('2026-09-15T12:00:00Z')).toMatch(/2026/);
  });
});

// --------------------------------------------------------------------- reads

describe('failing gracefully', () => {
  it('turns an HTTP status into a sentence a person can act on', () => {
    expect(reason(new ApiError('/x', 404, 'Not Found'))).toMatch(/no record of this yet/i);
    expect(reason(new ApiError('/x', 405, 'Method Not Allowed'))).toMatch(
      /does not answer this yet/i,
    );
    expect(reason(new ApiError('/x', 503, 'Unavailable'))).toMatch(
      /answered with an error \(503\)/,
    );
    expect(reason('a bare string')).toMatch(/did not say what/);
  });

  it('keeps one panel’s failure from costing the others', async () => {
    const ok = await settle(Promise.resolve([1, 2]));
    expect(ok).toEqual({ value: [1, 2], error: null });

    const bad = await settle(Promise.reject(new ApiError('/almanac/frost', 500, 'Boom')));
    expect(bad.value).toBeNull();
    expect(bad.error).toMatch(/error \(500\)/);
  });
});

describe('saving a correction', () => {
  it('patches this plant when the contract has an override field for it', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    await saveCareValue(
      { route: 'specimen', id: SPECIMEN_ID, overrideField: 'water_k_c_override' },
      0.8,
      fetcher as unknown as typeof fetch,
    );
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe(`/api/v1/specimens/${SPECIMEN_ID}`);
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ water_k_c_override: 0.8 });
  });

  it('puts a species care value where the contract records it on the species', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    await saveCareValue(
      { route: 'species', id: SPECIES_ID, field: 'light_label' },
      'full_sun',
      fetcher as unknown as typeof fetch,
    );
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe(`/api/v1/species/${SPECIES_ID}/care-values`);
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ field: 'light_label', value: 'full_sun' });
  });

  it('raises the failure rather than reporting a save that did not happen', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('', { status: 405, statusText: 'Method Not Allowed' }));
    await expect(
      saveCareValue(
        { route: 'species', id: SPECIES_ID, field: 'light_label' },
        'full_sun',
        fetcher as unknown as typeof fetch,
      ),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
