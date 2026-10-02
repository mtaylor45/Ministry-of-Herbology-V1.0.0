/** The relocation flow's own suite.
 *
 * the earlier deliverable is that completing "bring indoors" actually moves the plant,
 * and the thing worth testing is not that a POST is made — it is everything the
 * screen refuses to do on the reader's behalf: it does not guess a destination,
 * it does not let a move ride in a batch that cannot carry one, and it does not
 * stay quiet when there is nowhere to put the plant.
 *
 * Rendered through `svelte/server`, the way the rest of this parts of the project is
 * tested. The sheet's own interaction is driven in a real browser.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import Relocate from './Relocate.svelte';
import TaskRow from './TaskRow.svelte';
import BatchBar from './BatchBar.svelte';
import type { Location, Task } from './api';
import {
  ORIGIN_STORAGE_KEY,
  batchExclusionNotice,
  batchableIds,
  completingWithoutMoving,
  destinationsFor,
  direction,
  forgetOrigin,
  isRelocation,
  locationKind,
  locationName,
  locationOptions,
  nowhereToPut,
  readOrigins,
  relocationAnnouncement,
  relocationFailure,
  relocationPrompt,
  rememberOrigin,
  suggestedDestination,
  unbatchable,
} from './relocation';
import { completableIds } from './tasks';

const TODAY = new Date('2026-10-22T12:00:00Z');

function task(over: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    specimen: { id: 'spec-1', display_name: 'Basil the Bold', is_outdoor: true, thumb_url: null },
    task_type: 'bring_indoors',
    due_at: '2026-10-22T01:00:00Z',
    all_day: false,
    status: 'due',
    satisfied_by: null,
    amount_ml: null,
    priority: 'urgent',
    title: 'Shelter Basil the Bold from the frost',
    plain_title: 'Bring Basil the Bold indoors',
    detail: 'Forecast, not a measurement: the night is predicted to fall to 4 °C.',
    completed_at: null,
    completed_by: null,
    deep_link: '/specimen/spec-1/tending',
    confidence: 'high',
    degraded: false,
    degradations: [],
    ...over,
  };
}

function watering(over: Partial<Task> = {}): Task {
  return task({
    id: 'task-water',
    task_type: 'water',
    priority: 'normal',
    title: 'Tend Gilderoy',
    plain_title: 'Water Gilderoy — 450 ml',
    detail: null,
    ...over,
  });
}

const INSIDE: Location[] = [
  { id: 'loc-in-1', name: 'Greenhouse Window', kind: 'room', is_outdoor: false, is_covered: true },
  { id: 'loc-in-2', name: 'Kitchen Sill', kind: 'shelf', is_outdoor: false, is_covered: true },
];
const OUTSIDE: Location[] = [
  { id: 'loc-out-1', name: 'Back Terrace', kind: 'zone', is_outdoor: true, is_covered: false },
  { id: 'loc-out-2', name: 'Covered Porch', kind: 'zone', is_outdoor: true, is_covered: true },
];
const EVERYWHERE = [...INSIDE, ...OUTSIDE];

/** A `localStorage` the tests own. The real one is a browser's. */
function fakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    get size() {
      return store.size;
    },
  };
}

describe('which jobs move a plant', () => {
  it('knows the two the contract means, and no others', () => {
    expect(isRelocation(task({ task_type: 'bring_indoors' }))).toBe(true);
    expect(isRelocation(task({ task_type: 'return_outdoors' }))).toBe(true);
    // `cover` protects a plant where it stands. It moves nothing, so it takes
    // no destination — the same line `tending.domain` draws server-side.
    expect(isRelocation(task({ task_type: 'cover' }))).toBe(false);
    expect(isRelocation(watering())).toBe(false);
  });

  it('reads the direction off the task rather than off the plant', () => {
    expect(direction(task())).toBe('bring_indoors');
    expect(direction(task({ task_type: 'return_outdoors' }))).toBe('return_outdoors');
    expect(direction(watering())).toBeNull();
  });
});

describe('where a plant may go', () => {
  it('offers indoor places for a job that brings a plant in', () => {
    const places = destinationsFor(task(), EVERYWHERE);
    expect(places.every((place) => !place.is_outdoor)).toBe(true);
    expect(places).toHaveLength(INSIDE.length);
  });

  it('offers outdoor places for the reverse trip', () => {
    const places = destinationsFor(task({ task_type: 'return_outdoors' }), EVERYWHERE);
    expect(places.every((place) => place.is_outdoor)).toBe(true);
  });

  it('offers nothing at all for a job that moves nothing', () => {
    expect(destinationsFor(watering(), EVERYWHERE)).toEqual([]);
  });

  it('says what kind of place each one is, and whether it is covered', () => {
    expect(locationKind(INSIDE[0])).toBe('indoor room');
    expect(locationKind(OUTSIDE[0])).toMatch(/outdoor zone, open to the sky/);
    expect(locationKind(OUTSIDE[1])).toMatch(/outdoor zone, covered/);
  });

  it('leads each option with the place, because that is what is being chosen', () => {
    const options = locationOptions(INSIDE);
    expect(options[0].value).toBe('loc-in-1');
    expect(options[0].plain).toMatch(/^Greenhouse Window — /);
    expect(locationName(INSIDE, 'loc-in-2')).toBe('Kitchen Sill');
    expect(locationName(INSIDE, 'nothing')).toBeNull();
  });
});

describe('where it came from', () => {
  beforeEach(() => {
    (globalThis as { localStorage?: unknown }).localStorage = fakeStorage();
  });

  it('remembers the place a plant left, and offers it back', () => {
    rememberOrigin('spec-1', 'loc-out-1');
    const back = task({ task_type: 'return_outdoors' });
    expect(suggestedDestination(back, EVERYWHERE, readOrigins())).toEqual({
      locationId: 'loc-out-1',
      name: 'Back Terrace',
    });
  });

  it('suggests nothing for the trip inwards — an unchosen room is a wrong record', () => {
    rememberOrigin('spec-1', 'loc-out-1');
    expect(suggestedDestination(task(), EVERYWHERE, readOrigins())).toBeNull();
  });

  it('suggests nothing when the remembered place is no longer a place', () => {
    rememberOrigin('spec-1', 'loc-that-was-deleted');
    const back = task({ task_type: 'return_outdoors' });
    expect(suggestedDestination(back, EVERYWHERE, readOrigins())).toBeNull();
  });

  it('suggests nothing when the remembered place has stopped being outdoors', () => {
    rememberOrigin('spec-1', 'loc-in-1');
    const back = task({ task_type: 'return_outdoors' });
    expect(suggestedDestination(back, EVERYWHERE, readOrigins())).toBeNull();
  });

  it('forgets the origin once the plant is back out', () => {
    rememberOrigin('spec-1', 'loc-out-1');
    forgetOrigin('spec-1');
    expect(readOrigins()).toEqual({});
  });

  it('records nothing when the app did not know where the plant was', () => {
    rememberOrigin('spec-1', null);
    expect(readOrigins()).toEqual({});
  });

  it('survives storage that is switched off, or holding nonsense', () => {
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem() {
        throw new Error('blocked');
      },
      setItem() {
        throw new Error('blocked');
      },
    };
    expect(readOrigins()).toEqual({});
    expect(() => rememberOrigin('spec-1', 'loc-out-1')).not.toThrow();

    const storage = fakeStorage();
    storage.setItem(ORIGIN_STORAGE_KEY, '["not", "an", "object"]');
    (globalThis as { localStorage?: unknown }).localStorage = storage;
    expect(readOrigins()).toEqual({});

    storage.setItem(ORIGIN_STORAGE_KEY, '{"spec-1": 17, "spec-2": "loc-out-1"}');
    expect(readOrigins()).toEqual({ 'spec-2': 'loc-out-1' });
  });
});

describe('the batch cannot carry a move', () => {
  const round = [watering({ id: 'w1' }), task({ id: 'r1' }), watering({ id: 'w2' })];

  it('leaves relocations out of the select-all', () => {
    expect(batchableIds(round)).toEqual(['w1', 'w2']);
    expect(unbatchable(round).map((job) => job.id)).toEqual(['r1']);
  });

  it('drops a relocation even if a tick somehow reached it', () => {
    // Defence in depth: `POST /tending/tasks/complete-batch` takes `task_ids`
    // and `completed_by` and nothing else, so a batched move is a plant marked
    // sheltered while it stands in a freeze.
    expect(completableIds(round, new Set(['w1', 'r1']))).toEqual(['w1']);
  });

  it('says why the count on the button is smaller than the round', () => {
    const notice = batchExclusionNotice(unbatchable(round));
    expect(notice).toMatch(/One job/);
    expect(notice).toMatch(/bring indoors/i);
    expect(notice).toMatch(/where the plant went/i);
    expect(batchExclusionNotice([])).toBeNull();
  });

  it('counts more than one, and names each kind once', () => {
    const notice = batchExclusionNotice([
      task({ id: 'a' }),
      task({ id: 'b' }),
      task({ id: 'c', task_type: 'return_outdoors' }),
    ]);
    expect(notice).toMatch(/3 jobs/);
    expect(notice).toMatch(/bring indoors, put back outside/i);
  });
});

describe('what the reader is told', () => {
  it('asks a different question in each direction', () => {
    expect(relocationPrompt(task()).plain).toMatch(/carried to/);
    expect(relocationPrompt(task({ task_type: 'return_outdoors' })).plain).toMatch(/put outside/);
    for (const job of [task(), task({ task_type: 'return_outdoors' })]) {
      const prompt = relocationPrompt(job);
      expect(prompt.themed).not.toBe(prompt.plain);
      expect(prompt.plain.trim()).not.toBe('');
    }
  });

  it('treats a household with nowhere indoors as a household, not a fault', () => {
    const said = nowhereToPut(task());
    expect(said).toMatch(/No indoor location is on record/);
    expect(said).not.toMatch(/error|invalid|fail/i);
    expect(nowhereToPut(task({ task_type: 'return_outdoors' }))).toMatch(/No outdoor location/);
  });

  it('states what is lost by ticking it off without naming a place', () => {
    const said = completingWithoutMoving(task());
    expect(said).toMatch(/still be listed outdoors/);
    expect(said).toMatch(/frost guard/);
    expect(completingWithoutMoving(task({ task_type: 'return_outdoors' }))).toMatch(
      /still be listed indoors/,
    );
  });

  it('announces the place, in plain language, because the place is the point', () => {
    expect(relocationAnnouncement(task(), 'Greenhouse Window', 'Keeper')).toBe(
      'Basil the Bold moved to Greenhouse Window, recorded against Keeper.',
    );
    expect(relocationAnnouncement(task(), 'Greenhouse Window', null)).toBe(
      'Basil the Bold moved to Greenhouse Window.',
    );
    expect(relocationAnnouncement(task(), null, null)).toMatch(/no new location was recorded/);
  });

  it('says both halves failed, because G refuses the whole request', () => {
    const said = relocationFailure('The greenhouse would not accept that.');
    expect(said).toMatch(/plant was not moved/);
    expect(said).toMatch(/still on the round/);
  });
});

describe('a relocation row, rendered', () => {
  it('carries no checkbox, and says why', () => {
    const markup = html(TaskRow, { task: task(), now: TODAY });
    expect(markup).not.toContain('type="checkbox"');
    expect(text(markup)).toMatch(/has to say where the plant went/i);
  });

  it('still pairs the themed title with the plain one', () => {
    const markup = text(html(TaskRow, { task: task(), now: TODAY }));
    expect(markup).toContain('Shelter Basil the Bold from the frost');
    expect(markup).toContain('Bring Basil the Bold indoors');
  });

  it('says in the buttons accessible name that it will ask where', () => {
    expect(html(TaskRow, { task: task(), now: TODAY })).toContain(
      'aria-label="See it settled — mark done and say where it went: Bring Basil the Bold indoors"',
    );
  });

  it('marks an urgent job with a word, not only a colour', () => {
    const markup = text(html(TaskRow, { task: task(), now: TODAY }));
    expect(markup).toMatch(/Urgent — tonight, not tomorrow/);
    expect(text(html(TaskRow, { task: watering(), now: TODAY }))).not.toMatch(/Urgent/);
  });

  it('keeps a watering exactly as it was — checkbox, and a tick means selected', () => {
    const markup = html(TaskRow, { task: watering(), now: TODAY, selected: true });
    expect(markup).toContain('type="checkbox"');
    expect(text(markup)).toContain('Selected');
    expect(markup).toContain('data-meaning="selection"');
  });
});

describe('the relocation sheet, rendered', () => {
  const MEMBERS = [{ id: 'm-1', name: 'Keeper', role: 'keeper' }];
  const base = {
    open: true,
    task: task(),
    locations: EVERYWHERE,
    members: MEMBERS,
    memberId: 'm-1',
  };

  it('asks one question, and says why it is asking', () => {
    const markup = text(html(Relocate, base));
    expect(markup).toMatch(/Say where Basil the Bold was carried to/);
    expect(markup).toMatch(/next winter’s warnings/);
  });

  it('offers only indoor places for a job that brings a plant in', () => {
    const markup = html(Relocate, base);
    expect(markup).toContain('Greenhouse Window');
    expect(markup).toContain('Kitchen Sill');
    expect(markup).not.toContain('Back Terrace');
  });

  it('carries the forecast sentence and the confidence next to the instruction', () => {
    const markup = text(html(Relocate, base));
    expect(markup).toMatch(/Forecast, not a measurement/);
    expect(markup).toMatch(/High confidence/);
  });

  it('explains itself when there is nowhere of the right kind', () => {
    const markup = text(html(Relocate, { ...base, locations: OUTSIDE }));
    expect(markup).toMatch(/No indoor location is on record/);
    expect(markup).toMatch(/still be listed outdoors/);
  });

  it('starts on no destination, and says what that button will do', () => {
    const markup = text(html(Relocate, base));
    expect(markup).toContain('Mark done without recording a move');
    expect(markup).toMatch(/still be listed outdoors/);
  });

  it('starts on a remembered place for the trip back, and says where it got it', () => {
    const markup = text(
      html(Relocate, {
        ...base,
        task: task({ task_type: 'return_outdoors' }),
        suggestion: { locationId: 'loc-out-1', name: 'Back Terrace' },
      }),
    );
    expect(markup).toMatch(/last saw Basil the Bold leave Back Terrace/);
  });

  it('asks who carried it here, since this sheet is the completion', () => {
    const markup = text(html(Relocate, base));
    expect(markup).toContain('Who carried it');
    expect(markup).toContain('Keeper');
  });

  it('says plainly when there is nobody to attribute the move to', () => {
    expect(text(html(Relocate, { ...base, members: [], memberId: '' }))).toMatch(
      /will not say who did this/,
    );
  });

  it('keeps a failure on screen with the sheet, rather than closing over it', () => {
    const markup = html(Relocate, { ...base, failure: 'Nothing was recorded.' });
    expect(markup).toContain('role="alert"');
    expect(text(markup)).toContain('Nothing was recorded.');
  });
});

describe('the batch bar, with a move on the round', () => {
  const members = [{ id: 'm-1', name: 'Keeper', role: 'keeper' }];

  it('stops claiming to select every task due', () => {
    const withMove = text(
      html(BatchBar, {
        total: 6,
        selected: 0,
        checkState: 'unchecked',
        members,
        memberId: 'm-1',
        excluded: true,
      }),
    );
    expect(withMove).toContain('Select every task the batch can complete');

    const plain = text(
      html(BatchBar, { total: 6, selected: 0, checkState: 'unchecked', members, memberId: 'm-1' }),
    );
    expect(plain).toContain('Select every task due');
  });

  it('pairs both halves of its primary button again', () => {
    const markup = text(
      html(BatchBar, { total: 6, selected: 3, checkState: 'mixed', members, memberId: 'm-1' }),
    );
    // #26 shipped this plain-only to work around a 1.26:1 pairing. The design system's
    // `--moh-plain-ink` fixed it; the themed half belongs back.
    expect(markup).toContain('See to the lot');
    expect(markup).toContain('Mark 3 tasks done');
  });
});
