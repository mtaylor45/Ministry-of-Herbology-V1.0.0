/** The book must not be able to look complete while plants are missing from it.
 *
 * `plates.ts`, which is where the two things most worth getting right live:
 * which plant a plate belongs to, and what a reader is told about where the
 * picture came from.
 */

import { describe, expect, it } from 'vitest';
import {
  absenceCause,
  absenceSentence,
  coverageBySpecimen,
  altTextFor,
  buildPages,
  clampIndex,
  coverage,
  coverageSentence,
  creditLine,
  formatLicence,
  indexOfSpecimen,
  provenanceOf,
  type JournalPage,
} from './plates';
import type { JournalSpecimen, Plate, PlateCoverage, PlateCoverageEntry } from './api';

function specimen(id: string, name: string, speciesId?: string): JournalSpecimen {
  return {
    id,
    display_name: name,
    species: speciesId ? { id: speciesId, accepted_name: `Species ${speciesId}` } : null,
  };
}

function plate(overrides: Partial<Plate> = {}): Plate {
  return {
    id: 'plate-1',
    species_id: 'sp-1',
    specimen_id: null,
    image_url: '/api/v1/journal/plates/plate-1/image',
    thumb_url: null,
    origin: 'public_domain',
    license: 'public domain',
    attribution: 'A collection that stated the licence',
    approved: true,
    ...overrides,
  };
}

describe('the book pages through plants, not plates', () => {
  it('gives every specimen a leaf, with or without a plate', () => {
    const pages = buildPages(
      [specimen('s1', 'Gilderoy', 'sp-1'), specimen('s2', 'Nobody', 'sp-9')],
      [plate()],
    );
    expect(pages).toHaveLength(2);
    expect(pages[0].state).toBe('plate');
    expect(pages[1].state).toBe('absent');
  });

  it('keeps register order so the book does not reshuffle itself', () => {
    const pages = buildPages(
      [specimen('s1', 'First', 'sp-1'), specimen('s2', 'Second', 'sp-2')],
      [plate({ id: 'p2', species_id: 'sp-2' })],
    );
    expect(pages.map((page) => page.specimen.id)).toEqual(['s1', 's2']);
  });

  it('never borrows another species plate', () => {
    const pages = buildPages([specimen('s1', 'Gilderoy', 'sp-1')], [plate({ species_id: 'sp-2' })]);
    expect(pages[0].plate).toBeNull();
    expect(pages[0].state).toBe('absent');
  });

  it('never gives a plate to a specimen with no species recorded', () => {
    const pages = buildPages([specimen('s1', 'Mystery')], [plate()]);
    expect(pages[0].plate).toBeNull();
  });

  it('prefers a plate of this actual plant over its species plate', () => {
    const own = plate({ id: 'own', specimen_id: 's1', species_id: null, origin: 'user_upload' });
    const shared = plate({ id: 'shared', species_id: 'sp-1' });
    const pages = buildPages([specimen('s1', 'Gilderoy', 'sp-1')], [shared, own]);
    expect(pages[0].plate?.id).toBe('own');
  });

  it('shows an unapproved plate rather than hiding it', () => {
    const pages = buildPages([specimen('s1', 'Gilderoy', 'sp-1')], [plate({ approved: false })]);
    expect(pages[0].state).toBe('waiting');
    expect(pages[0].plate).not.toBeNull();
  });

  it('finds a plant in the book, and says so when it is not there', () => {
    const pages = buildPages([specimen('s1', 'A', 'sp-1'), specimen('s2', 'B', 'sp-2')], []);
    expect(indexOfSpecimen(pages, 's2')).toBe(1);
    expect(indexOfSpecimen(pages, 's9')).toBeNull();
  });
});

describe('coverage is reported, never rounded up', () => {
  const pages = buildPages(
    [
      specimen('s1', 'Approved', 'sp-1'),
      specimen('s2', 'Waiting', 'sp-2'),
      specimen('s3', 'Drawn', 'sp-3'),
      specimen('s4', 'Nothing', 'sp-4'),
    ],
    [
      plate({ id: 'p1', species_id: 'sp-1' }),
      plate({ id: 'p2', species_id: 'sp-2', approved: false }),
      plate({
        id: 'p3',
        species_id: 'sp-3',
        origin: 'generated',
        license: null,
        attribution: null,
      }),
    ],
  );

  it('counts what is actually there', () => {
    expect(coverage(pages)).toEqual({
      total: 4,
      approved: 2,
      waiting: 1,
      absent: 1,
      generated: 1,
      sourced: 2,
    });
  });

  it('says the gap out loud', () => {
    const sentence = coverageSentence(coverage(pages));
    expect(sentence).toContain('2 of 4');
    expect(sentence).toContain('1 with no plate at all');
    expect(sentence).toContain('drawn by software');
  });

  it('does not claim a book exists when the register is empty', () => {
    expect(coverageSentence(coverage([]))).toContain('no plants in the register');
  });

  it('leaves out the clauses that would be zero', () => {
    const complete = buildPages([specimen('s1', 'A', 'sp-1')], [plate()]);
    const sentence = coverageSentence(coverage(complete));
    expect(sentence).toBe('1 of 1 plants have an approved plate.');
  });
});

describe('a generated plate cannot pass as a collected one', () => {
  const generated = plate({ origin: 'generated', license: null, attribution: null });

  it('is labelled "drawn", not caveated', () => {
    const note = provenanceOf(generated);
    expect(note.kind).toBe('drawn');
    expect(note.plain).toContain('generated by software');
    expect(note.plain).toContain('not a historical plate');
  });

  it('carries no credit, because there is none to carry', () => {
    expect(provenanceOf(generated).credit).toBeNull();
    expect(creditLine(generated)).toBeNull();
  });

  it('says so inside the alt text too, not only in the visible caption', () => {
    const [page] = buildPages([specimen('s1', 'Drawn', 'sp-1')], [generated]);
    const alt = altTextFor(page);
    expect(alt).toContain('generated by software');
    expect(alt).toContain('not a scan of a historical plate');
  });

  it('is told apart from a collected plate in both places', () => {
    const [collected] = buildPages([specimen('s1', 'Collected', 'sp-1')], [plate()]);
    expect(altTextFor(collected)).not.toContain('generated');
    expect(provenanceOf(plate()).kind).toBe('collected');
  });
});

describe('a collected plate shows what it earned', () => {
  it('puts the credit and the licence in one line', () => {
    expect(creditLine(plate())).toBe('A collection that stated the licence — Public domain');
  });

  it('shows a licence with no credit, and a credit with no licence', () => {
    expect(creditLine(plate({ attribution: null }))).toBe('Public domain');
    expect(creditLine(plate({ license: null }))).toBe('A collection that stated the licence');
  });

  it('names the collection in the alt text', () => {
    const [page] = buildPages([specimen('s1', 'Collected', 'sp-1')], [plate()]);
    expect(altTextFor(page)).toContain('from a public collection');
    expect(altTextFor(page)).toContain('A collection that stated the licence');
  });

  it('reads a licence back the way a caption should spell it', () => {
    expect(formatLicence('public domain')).toBe('Public domain');
    expect(formatLicence('cc by-sa 4.0')).toBe('CC BY-SA 4.0');
    expect(formatLicence('cc0 1.0')).toBe('CC0 1.0');
  });

  it('describes a household photograph as a photograph', () => {
    const own = plate({ origin: 'user_upload', license: null, attribution: null });
    const [page] = buildPages([specimen('s1', 'Gilderoy', 'sp-1')], [own]);
    expect(provenanceOf(own).kind).toBe('own');
    expect(altTextFor(page)).toContain('photograph');
  });

  it('gives an absent page no alt text, because there is no image', () => {
    const [page] = buildPages([specimen('s1', 'Nothing', 'sp-9')], []);
    expect(altTextFor(page)).toBe('');
  });
});

describe('a blank leaf names the plant and invents no cause', () => {
  const [page] = buildPages([specimen('s1', 'Nothing', 'sp-9')], []);

  it('names the plant', () => {
    expect(absenceSentence(page)).toContain('Species sp-9');
  });

  it('says what the journal will not do instead', () => {
    expect(absenceSentence(page)).toContain("another plant's picture");
  });

  it('falls back to the display name when no botanical name is known', () => {
    const [unnamed] = buildPages([specimen('s2', 'Just a nickname')], []);
    expect(absenceSentence(unnamed)).toContain('Just a nickname');
  });
});

describe('paging cannot leave the book', () => {
  const pages: JournalPage[] = buildPages(
    [specimen('s1', 'A', 'sp-1'), specimen('s2', 'B', 'sp-2'), specimen('s3', 'C', 'sp-3')],
    [],
  );

  it('clamps a bad index to a real leaf', () => {
    expect(clampIndex(-4, pages)).toBe(0);
    expect(clampIndex(99, pages)).toBe(2);
    expect(clampIndex(1, pages)).toBe(1);
  });

  it('survives a nonsense index from a URL', () => {
    expect(clampIndex(Number.NaN, pages)).toBe(0);
    expect(clampIndex(1.7, pages)).toBe(1);
  });

  it('has nowhere to go in an empty book', () => {
    expect(clampIndex(3, [])).toBe(0);
  });
});

describe('a blank leaf says which of the six cases it is', () => {
  const [page] = buildPages([specimen('s1', 'Nothing', 'sp-9')], []);

  function entry(kind: PlateCoverageEntry['reason_kind']): PlateCoverageEntry {
    return {
      specimen: { id: 's1', display_name: 'Nothing' },
      state: 'absent',
      plate_id: null,
      reason_kind: kind,
      reason: 'the pipeline said so',
    };
  }

  it('names the plant whichever cause applies', () => {
    for (const kind of [
      'no_candidate',
      'unlicensed_candidate',
      'generation_unavailable',
      'unusable_image',
      'store_unavailable',
      'not_run',
    ] as const) {
      expect(absenceSentence(page, entry(kind))).toContain('Species sp-9');
    }
  });

  it('gives every kind in the closed set its own words', () => {
    const causes = (
      [
        'no_candidate',
        'unlicensed_candidate',
        'generation_unavailable',
        'unusable_image',
        'store_unavailable',
        'not_run',
      ] as const
    ).map((kind) => absenceCause(entry(kind)));
    expect(causes.every((c) => typeof c === 'string' && c.length > 0)).toBe(true);
    expect(new Set(causes).size).toBe(causes.length);
  });

  it('does not say "nothing was found" when the volume is unmounted', () => {
    const sentence = absenceSentence(page, entry('store_unavailable'));
    expect(sentence).toContain('nowhere to keep plates');
    expect(sentence).not.toContain('Every catalogue');
  });

  it('does not say "nothing was found" when nothing has looked', () => {
    const sentence = absenceSentence(page, entry('not_run'));
    expect(sentence).toContain('Nothing has looked for one yet');
  });

  it('says a discarded candidate was discarded, not relabelled', () => {
    expect(absenceSentence(page, entry('unlicensed_candidate'))).toContain(
      'discarded rather than relabelled',
    );
  });

  it('falls back to the generic sentence when coverage did not answer', () => {
    const sentence = absenceSentence(page);
    expect(sentence).toContain('or has not run for this plant');
    expect(sentence).toContain("another plant's picture");
  });

  it('falls back rather than rendering a blank for an unknown kind', () => {
    const seventh = { ...entry('not_run'), reason_kind: 'something_new' } as never;
    expect(absenceCause(seventh)).toBeNull();
    expect(absenceSentence(page, seventh)).toContain('or has not run for this plant');
  });

  it("still refuses to borrow another plant's picture, whatever the cause", () => {
    expect(absenceSentence(page, entry('no_candidate'))).toContain("another plant's picture");
  });
});

describe('coverage entries are paired to leaves by specimen', () => {
  const coverage: PlateCoverage = {
    total: 2,
    approved: 0,
    waiting: 0,
    absent: 2,
    generated: 0,
    specimens: [
      {
        specimen: { id: 's1', display_name: 'A' },
        state: 'absent',
        plate_id: null,
        reason_kind: 'no_candidate',
        reason: 'r1',
      },
      {
        specimen: { id: 's2', display_name: 'B' },
        state: 'absent',
        plate_id: null,
        reason_kind: 'not_run',
        reason: 'r2',
      },
    ],
  };

  it('finds each plant its own entry', () => {
    const by = coverageBySpecimen(coverage);
    expect(by.get('s1')?.reason_kind).toBe('no_candidate');
    expect(by.get('s2')?.reason_kind).toBe('not_run');
  });

  it('is empty rather than throwing when coverage failed', () => {
    expect(coverageBySpecimen(null).size).toBe(0);
  });
});
