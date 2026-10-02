import { describe, expect, it } from 'vitest';
import { candidateLabel, createBody, knownSpeciesId } from './addPlant';
import {
  NO_FILTERS,
  describeFilters,
  emptySentence,
  filterParams,
  groupLine,
  hasFilters,
  nextTaskLine,
  parseFilters,
  placeLine,
  registerHref,
  speciesIndex,
  speciesLine,
  specimensPath,
  summarySentence,
  toxicityMark,
  type RegisterLocation,
  type RegisterSpecimen,
} from './register';

const STUDY: RegisterLocation = {
  id: '01890010-0000-7000-8000-000000000002',
  name: 'Study',
  kind: 'room',
  is_outdoor: false,
};

const plant = (over: Partial<RegisterSpecimen> = {}): RegisterSpecimen => ({
  id: 'p1',
  display_name: 'Gilderoy',
  species: { id: 's1', accepted_name: 'Monstera deliciosa', common_name: 'Swiss cheese plant' },
  is_outdoor: false,
  location: STUDY,
  status: 'thriving',
  ...over,
});

describe('a filter is an address', () => {
  it('reads every filter the contract serves', () => {
    const f = parseFilters(
      new URLSearchParams(
        `q=basil&location_id=${STUDY.id}&outdoor=false&status=dormant&toxic_to_pets=true`,
      ),
    );
    expect(f).toEqual({
      q: 'basil',
      location_id: STUDY.id,
      outdoor: 'false',
      status: 'dormant',
      toxic_to_pets: 'true',
    });
  });

  it('drops what the API would refuse, so a bad bookmark shows the Register, not a 422', () => {
    const f = parseFilters(
      new URLSearchParams('status=active&location_id=study&outdoor=maybe&toxic_to_pets=1'),
    );
    expect(f).toEqual(NO_FILTERS);
  });

  it('round-trips, leaving empty filters out of the address', () => {
    const href = registerHref({ ...NO_FILTERS, q: 'basil', status: 'archived' });
    expect(href).toBe('/register?q=basil&status=archived');
    expect(parseFilters(new URL(href, 'http://x').searchParams).status).toBe('archived');
    expect(registerHref(NO_FILTERS)).toBe('/register');
  });

  it('pages with a cursor and a limit, never a page number', () => {
    expect(specimensPath({ ...NO_FILTERS, q: 'mint' }, 'abc')).toBe(
      '/specimens?q=mint&limit=25&cursor=abc',
    );
    expect(specimensPath(NO_FILTERS, null)).toBe('/specimens?limit=25');
  });

  it('knows whether any filter is set', () => {
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, outdoor: 'true' })).toBe(true);
    expect(filterParams({ ...NO_FILTERS, q: '   ' }).toString()).toBe('');
  });
});

describe('a row', () => {
  it('names the species, common name first, and says so when it is unknown', () => {
    expect(speciesLine(plant())).toBe('Swiss cheese plant · Monstera deliciosa');
    expect(speciesLine(plant({ species: null }))).toBe('Species not yet identified');
    expect(
      speciesLine(plant({ cultivar: 'Thai', species: { accepted_name: 'Ocimum basilicum' } })),
    ).toBe('Ocimum basilicum ‘Thai’');
  });

  it('does not repeat a common name that is already the display name', () => {
    expect(
      speciesLine(
        plant({
          display_name: 'English lavender',
          species: { accepted_name: 'Lavandula angustifolia', common_name: 'English lavender' },
        }),
      ),
    ).toBe('Lavandula angustifolia');
  });

  it('says where it stands, and in or out, even with no location', () => {
    expect(placeLine(plant())).toBe('Study (room) · indoors');
    expect(placeLine(plant({ location: null, is_outdoor: true }))).toBe(
      'No location recorded · outdoors',
    );
  });

  it('says a group is a group, with its count', () => {
    expect(groupLine(plant())).toBeNull();
    expect(groupLine(plant({ is_group: true, count: 9 }))).toBe('A group of 9 plants');
  });

  it('describes the next task when there is one and says nothing when there is not', () => {
    const now = new Date(2026, 9, 2, 9);
    expect(nextTaskLine(null, now)).toBeNull();
    expect(
      nextTaskLine(
        { plain_title: 'Water the basil', due_at: new Date(2026, 9, 2, 18).toISOString() },
        now,
      ),
    ).toBe('Next: Water the basil, due today');
    expect(
      nextTaskLine({ task_type: 'mist', due_at: new Date(2026, 9, 1).toISOString() }, now),
    ).toBe('Next: mist, overdue');
  });
});

describe('the toxicity mark is words, and unknown is never safe', () => {
  const index = speciesIndex([
    { id: 's1', toxic_to_pets: true, toxic_to_children: true },
    { id: 's2', toxic_to_pets: false, toxic_to_children: false },
    { id: 's3', toxic_to_pets: null, toxic_to_children: false },
    { id: 's4', toxic_to_pets: true, toxic_to_children: null },
  ]);
  const of = (id: string | undefined) =>
    toxicityMark(plant({ species: id ? { id, accepted_name: 'X' } : null }), index);

  it('warns in words', () => {
    expect(of('s1')).toEqual({ text: 'Toxic to pets and children', warn: true });
    expect(of('s4')).toEqual({ text: 'Toxic to pets', warn: true });
  });

  it('says not known to be toxic only when both flags are false', () => {
    expect(of('s2')).toEqual({ text: 'Not known to be toxic', warn: false });
  });

  it('calls a null, an unlisted species and no species "not checked"', () => {
    expect(of('s3').text).toBe('Toxicity not checked');
    expect(of('missing').text).toBe('Toxicity not checked');
    expect(of(undefined).text).toBe('Toxicity not checked');
  });

  it('says the list could not be read rather than drawing no warning', () => {
    expect(toxicityMark(plant(), null).text).toBe('Toxicity could not be read');
  });
});

describe('summaries and empty states', () => {
  it('counts the Register and says when only the first page is showing', () => {
    expect(summarySentence(12, 12, NO_FILTERS, [])).toBe('12 entries in the Register.');
    expect(summarySentence(25, 40, NO_FILTERS, [])).toBe(
      '40 entries in the Register. Showing the first 25.',
    );
  });

  it('names the filters in the summary', () => {
    expect(
      summarySentence(1, 1, { ...NO_FILTERS, location_id: STUDY.id, status: 'dormant' }, [STUDY]),
    ).toBe('1 entry at Study, with status “Dormant”.');
  });

  it('tells an empty household how to add a plant', () => {
    const e = emptySentence(NO_FILTERS, []);
    expect(e.plain).toBe('No plants in the Register yet');
    expect(e.body).toMatch(/Add a plant/);
  });

  it('tells a filter with no matches which filter', () => {
    const e = emptySentence({ ...NO_FILTERS, q: 'fern', toxic_to_pets: 'true' }, []);
    expect(e.plain).toBe('Nothing matches these filters');
    expect(e.body).toBe(
      'No entry matching “fern”, toxic to pets. Clear a filter to widen the search.',
    );
  });

  it('describes the "not toxic" filter without calling it safe', () => {
    expect(describeFilters({ ...NO_FILTERS, toxic_to_pets: 'false' }, [])).toEqual([
      'not marked toxic to pets',
    ]);
  });
});

describe('adding a plant', () => {
  const basil = {
    accepted_name: 'Ocimum basilicum',
    common_name: 'sweet basil',
    family: 'Lamiaceae',
    confidence: 'high' as const,
    source: { title: 'GBIF Backbone Taxonomy' },
  };

  it('describes a candidate with its confidence and source', () => {
    expect(candidateLabel(basil)).toBe(
      'Ocimum basilicum · sweet basil · Lamiaceae — high confidence (GBIF Backbone Taxonomy)',
    );
  });

  it('matches a candidate to a species the household already has', () => {
    const species = [
      {
        id: 's5',
        accepted_name: 'Ocimum basilicum',
        toxic_to_pets: false,
        toxic_to_children: false,
      },
    ];
    expect(knownSpeciesId(basil, species)).toBe('s5');
    expect(knownSpeciesId({ ...basil, accepted_name: 'Mentha spicata' }, species)).toBeNull();
  });

  it('sends the chosen name and leaves empty optional fields out', () => {
    expect(
      createBody({
        typed: 'basil',
        candidate: basil,
        speciesId: 's5',
        nickname: ' ',
        locationId: '',
        count: 1,
      }),
    ).toEqual({ name: 'Ocimum basilicum', species_id: 's5' });
  });

  it('sends the typed name when no candidate was chosen', () => {
    expect(
      createBody({
        typed: ' moonflower ',
        candidate: null,
        speciesId: null,
        nickname: 'Lune',
        locationId: STUDY.id,
        count: 3,
      }),
    ).toEqual({ name: 'moonflower', nickname: 'Lune', location_id: STUDY.id, count: 3 });
  });
});
