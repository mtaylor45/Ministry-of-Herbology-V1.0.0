/** Morning Rounds' own suite.
 *
 * Rendered through `svelte/server`, the way the design system's library and the
 * Almanac are tested, so the screen is checked without adding a DOM emulator to
 * a `package.json` this parts of the project does not own. Everything that decides what a
 * reader is told is a pure function in `tasks.ts` and is tested directly.
 *
 * The interactive half — ticking boxes, posting a batch, the live region — is
 * driven in a real browser against the running API rather than asserted here;
 * what this file protects is the wording and the arithmetic behind it.
 */

import { describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import BatchBar from './BatchBar.svelte';
import TaskRow from './TaskRow.svelte';
import Unscheduled from './Unscheduled.svelte';
import type { Task } from './api';
import {
  CERTAINTY_SILENCE,
  UNSCHEDULED_SILENCE,
  batchButtonPlain,
  completableIds,
  completionAnnouncement,
  completionFailure,
  daysBetween,
  dueSentence,
  initialMember,
  instructionNote,
  memberName,
  reportsUnscheduled,
  satisfiedStatus,
  taskConfidence,
  taskMeta,
  tasksReportCertainty,
  unscheduledRows,
} from './tasks';

const TODAY = new Date('2026-09-24T12:00:00Z');

function task(over: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    specimen: { id: 'spec-1', display_name: 'Gilderoy', is_outdoor: false, thumb_url: null },
    task_type: 'water',
    due_at: '2026-09-24T09:00:00Z',
    all_day: true,
    status: 'due',
    satisfied_by: null,
    amount_ml: 450,
    priority: 'normal',
    title: 'Tend Gilderoy',
    plain_title: 'Water Gilderoy — 450 ml',
    detail: null,
    completed_at: null,
    completed_by: null,
    deep_link: '/specimen/spec-1/tending',
    confidence: 'medium',
    degraded: false,
    degradations: [],
    ...over,
  };
}

describe('when a task was owed', () => {
  it('counts whole days, not hours', () => {
    expect(daysBetween('2026-09-24T09:00:00Z', TODAY)).toBe(0);
    expect(daysBetween('2026-09-23T23:00:00Z', TODAY)).toBe(1);
    expect(daysBetween('2026-09-09T09:00:00Z', TODAY)).toBe(15);
  });

  it('survives a due date it cannot read rather than printing NaN', () => {
    expect(daysBetween('not a date', TODAY)).toBe(0);
    expect(dueSentence(task({ due_at: 'not a date' }), TODAY)).toBe('due today');
  });

  it('says today, a day, or a count of days', () => {
    expect(dueSentence(task(), TODAY)).toBe('due today');
    expect(dueSentence(task({ due_at: '2026-09-23T09:00:00Z' }), TODAY)).toBe('a day overdue');
    expect(dueSentence(task({ due_at: '2026-09-09T09:00:00Z' }), TODAY)).toBe('15 days overdue');
  });

  it('puts the job, the lateness and the amount in the second line', () => {
    expect(taskMeta(task(), TODAY)).toBe('Water · due today · 450 ml');
    expect(taskMeta(task({ task_type: 'repot', amount_ml: null }), TODAY)).toBe(
      'Repot · due today',
    );
  });

  it('names a task type it has never heard of rather than dropping it', () => {
    expect(taskMeta(task({ task_type: 'incantation', amount_ml: null }), TODAY)).toBe(
      'incantation · due today',
    );
  });
});

describe('satisfied is not done', () => {
  it('names what settled the watering, plainly as well as themed', () => {
    expect(satisfiedStatus(task({ satisfied_by: 'rain' })).plain).toBe('Rain covered it');
    expect(satisfiedStatus(task({ satisfied_by: 'sensor' })).plain).toBe(
      'Sensor says no water needed',
    );
    expect(satisfiedStatus(task({ satisfied_by: 'forecast_change' })).plain).toMatch(/forecast/i);
    expect(satisfiedStatus(task({ satisfied_by: 'manual' })).plain).toMatch(/person/i);
  });

  it('says the API did not say, rather than guessing at rain', () => {
    const status = satisfiedStatus(task({ satisfied_by: null }));
    expect(status.plain).toMatch(/did not say/i);
  });

  it('never calls a settled task done', () => {
    for (const by of ['rain', 'sensor', 'forecast_change', 'manual', null] as const) {
      expect(satisfiedStatus(task({ satisfied_by: by })).plain.toLowerCase()).not.toContain('done');
    }
  });
});

describe('how sure the scheduler is', () => {
  it('has a sentence for each of design decision 0004s four levels', () => {
    expect(taskConfidence('high').plain).toMatch(/high/i);
    expect(taskConfidence('medium').plain).toMatch(/medium/i);
    expect(taskConfidence('low').plain).toMatch(/low/i);
    expect(taskConfidence('unknown').plain).toMatch(/unknown/i);
  });

  it('does not read an absent confidence as a high one', () => {
    // A completed task cannot say how sure it was: the frozen `task` table has
    // no column its confidence could have been kept in.
    expect(taskConfidence(null).plain).toMatch(/does not say/i);
    expect(taskConfidence(undefined).plain).toMatch(/does not say/i);
    expect(taskConfidence(null).plain).not.toBe(taskConfidence('high').plain);
  });

  it('does not borrow the Almanacs vocabulary for a plant fact', () => {
    // "Read through cloud" is right for a forecast and wrong for an interval
    // nobody cited, which is not a reading at all.
    expect(taskConfidence('medium').themed).not.toMatch(/read/i);
  });

  it('prints the plain detail only when there is no structured reason', () => {
    const detail = 'This is a guess, not a measurement.';
    expect(instructionNote(task({ detail }))).toBe(detail);
    expect(
      instructionNote(
        task({ detail, degradations: [{ code: 'x', detail: 'Something', caps_at: 'low' }] }),
      ),
    ).toBeNull();
    expect(instructionNote(task({ detail: '   ' }))).toBeNull();
  });

  it('tells a silent payload from a confident one', () => {
    expect(tasksReportCertainty([task()])).toBe(true);
    expect(tasksReportCertainty([task({ confidence: null, degraded: undefined })])).toBe(true);
    const legacy = task();
    delete legacy.confidence;
    delete legacy.degraded;
    expect(tasksReportCertainty([legacy])).toBe(false);
    expect(tasksReportCertainty([])).toBe(false);
  });

  it('says what a silence means rather than showing a clean blank', () => {
    expect(CERTAINTY_SILENCE).toMatch(/uncited/i);
  });
});

describe('the plants nothing was scheduled for', () => {
  it('tells "none were left off" from "the API never said"', () => {
    expect(
      reportsUnscheduled({ date: '', due: [], satisfied: [], alerts: [], unscheduled: [] }),
    ).toBe(true);
    expect(reportsUnscheduled({ date: '', due: [], satisfied: [], alerts: [] })).toBe(false);
    expect(reportsUnscheduled(null)).toBe(false);
  });

  it('warns in so many words when the field is missing', () => {
    expect(UNSCHEDULED_SILENCE).toMatch(/looks exactly like a plant that needs nothing/);
  });

  it('names the plant where the register can, and says so where it cannot', () => {
    const rows = unscheduledRows(
      [
        { specimen_id: 'spec-1', reason: 'No watering interval anywhere.' },
        { specimen_id: 'spec-9', reason: 'Dormant this month.' },
      ],
      [{ id: 'spec-1', display_name: 'Gilderoy' }],
    );
    expect(rows[0]).toMatchObject({
      name: 'Gilderoy',
      named: true,
      reason: 'No watering interval anywhere.',
    });
    expect(rows[1].named).toBe(false);
    expect(rows[1].reason).toBe('Dormant this month.');
    // Every row leads somewhere a care value can be set.
    expect(rows.map((row) => row.href)).toEqual([
      '/specimen/spec-1/tending',
      '/specimen/spec-9/tending',
    ]);
  });

  it('still shows the reasons when the register could not be read at all', () => {
    const rows = unscheduledRows([{ specimen_id: 'spec-1', reason: 'No interval.' }], null);
    expect(rows[0].named).toBe(false);
    expect(rows[0].reason).toBe('No interval.');
  });
});

describe('who did it, and what was done', () => {
  const members = [
    { id: 'm-1', name: 'Keeper', role: 'keeper' },
    { id: 'm-2', name: 'Miriam', role: 'tender' },
  ];

  it('starts on the member this device used last', () => {
    expect(initialMember(members, 'm-2')).toBe('m-2');
  });

  it('does not guess the first member of a household of several', () => {
    expect(initialMember(members, 'm-9')).toBe('');
    expect(initialMember(members, null)).toBe('');
    expect(initialMember([], 'm-1')).toBe('');
  });

  it('starts on the only member of a household of one', () => {
    expect(initialMember([members[0]], null)).toBe('m-1');
  });

  it('names a member', () => {
    expect(memberName(members, 'm-2')).toBe('Miriam');
    expect(memberName(members, 'nobody')).toBeNull();
  });

  it('announces the count and the member in plain language', () => {
    expect(completionAnnouncement(3, 'Miriam')).toBe(
      '3 tasks marked done, recorded against Miriam.',
    );
    expect(completionAnnouncement(1, 'Miriam')).toBe(
      '1 task marked done, recorded against Miriam.',
    );
  });

  it('says outright when nothing was attributed', () => {
    expect(completionAnnouncement(2, null)).toMatch(/No household member was recorded/);
  });

  it('counts what the button will do', () => {
    expect(batchButtonPlain(0)).toMatch(/nothing selected/i);
    expect(batchButtonPlain(1)).toBe('Mark 1 task done');
    expect(batchButtonPlain(4)).toBe('Mark 4 tasks done');
  });

  it('promises the selection is kept when a batch fails', () => {
    expect(completionFailure('The greenhouse refused the request (422).')).toMatch(
      /selection has been kept/i,
    );
  });

  it('sends only ticks that are still on the round', () => {
    const due = [task({ id: 'a' }), task({ id: 'b' })];
    expect(completableIds(due, new Set(['a', 'gone']))).toEqual(['a']);
    expect(completableIds(due, new Set())).toEqual([]);
  });
});

describe('a task, rendered', () => {
  it('never shows the themed title without the plain one', () => {
    const markup = text(html(TaskRow, { task: task(), now: TODAY }));
    expect(markup).toContain('Tend Gilderoy');
    expect(markup).toContain('Water Gilderoy — 450 ml');
  });

  it('names the plant in the completion buttons accessible name', () => {
    const markup = html(TaskRow, { task: task(), now: TODAY });
    expect(markup).toContain('aria-label="Done and dusted — mark done: Water Gilderoy — 450 ml"');
  });

  it('shows every degradation sentence as the engine wrote it', () => {
    const degradations = [
      {
        code: 'interval_uncited',
        detail: 'The watering interval for Gilderoy carries no citation.',
        caps_at: 'unknown' as const,
      },
      {
        code: 'balance_stale',
        detail: 'The water balance behind this task was last advanced four days ago.',
        caps_at: 'low' as const,
      },
    ];
    const markup = text(
      html(TaskRow, {
        task: task({ degraded: true, confidence: 'unknown', degradations }),
        now: TODAY,
      }),
    );
    for (const degradation of degradations) expect(markup).toContain(degradation.detail);
    // The ceiling each one puts on the answer, said in words.
    expect(markup).toContain('Caps this answer at');
  });

  it('puts the caveat in the row, not behind a tap', () => {
    const markup = html(TaskRow, {
      task: task({
        degraded: true,
        degradations: [{ code: 'x', detail: 'A reason.', caps_at: 'low' }],
      }),
      now: TODAY,
    });
    expect(markup).not.toContain('<details');
    expect(markup).not.toContain('title="A reason."');
  });

  it('calls a ticked box selected, not done', () => {
    const markup = text(html(TaskRow, { task: task(), now: TODAY, selected: true }));
    expect(markup).toContain('Selected');
    expect(markup).not.toMatch(/\bDone\b(?!\s+and\s+dusted)/);
  });

  it('carries a link to the plant it is about', () => {
    expect(html(TaskRow, { task: task(), now: TODAY })).toContain(
      'href="/specimen/spec-1/tending"',
    );
  });
});

describe('the batch bar, rendered', () => {
  const members = [{ id: 'm-1', name: 'Keeper', role: 'keeper' }];

  it('says how much of the round is selected, in words', () => {
    const markup = text(
      html(BatchBar, { total: 9, selected: 3, checkState: 'mixed', members, memberId: 'm-1' }),
    );
    expect(markup).toContain('3 of 9 selected');
    expect(markup).toContain('Mark 3 tasks done');
  });

  it('carries the mixed state on the select-all control for a screen reader', () => {
    const markup = html(BatchBar, {
      total: 9,
      selected: 3,
      checkState: 'mixed',
      members,
      memberId: 'm-1',
    });
    expect(markup).toContain('aria-checked="mixed"');
  });

  it('says plainly when there is nobody to attribute a completion to', () => {
    const markup = text(
      html(BatchBar, { total: 2, selected: 0, checkState: 'unchecked', members: [], memberId: '' }),
    );
    expect(markup).toMatch(/no members on record/i);
  });
});

describe('the unscheduled panel, rendered', () => {
  it('shows each plants reason in the schedulers own words', () => {
    const markup = text(
      html(Unscheduled, {
        rows: unscheduledRows(
          [{ specimen_id: 'spec-1', reason: 'No watering interval anywhere.' }],
          [{ id: 'spec-1', display_name: 'Gilderoy' }],
        ),
      }),
    );
    expect(markup).toContain('Gilderoy');
    expect(markup).toContain('No watering interval anywhere.');
    expect(markup).toMatch(/not the same as needing nothing/i);
  });
});
