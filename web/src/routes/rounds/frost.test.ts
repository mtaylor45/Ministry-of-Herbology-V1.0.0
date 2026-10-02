/** The frost watch, and how urgently a job asks.
 *
 * the earlier third deliverable: the frost guard is live on surfaces that already
 * existed, and the screen has to stop showing three different things as one.
 * A night still ahead is a warning, tonight is an instruction, and a night
 * behind us is a record of something that either was done or was not.
 */

import { describe, expect, it } from 'vitest';
import { html, text } from '$ui/render';
import FrostWatch from './FrostWatch.svelte';
import TaskRow from './TaskRow.svelte';
import type { FrostAlert, Task } from './api';
import {
  alertActionPlain,
  alertGroups,
  alertMeasurements,
  alertTaskId,
  hasUrgent,
  nightWhen,
  taskUrgency,
} from './tasks';

const ROUND_DATE = '2026-10-22';

function alert(over: Partial<FrostAlert> = {}): FrostAlert {
  return {
    id: 'alert-1',
    specimen: { id: 'spec-1', display_name: 'Basil the Bold', is_outdoor: true, thumb_url: null },
    night_of: ROUND_DATE,
    forecast_low_c: 4,
    threshold_c: 11.67,
    action: 'bring_indoors',
    advisory: 'Freeze Warning in effect from 2 AM to 9 AM',
    task_id: 'task-1',
    state: 'open',
    confidence: 'high',
    degraded: false,
    degradations: [],
    ...over,
  };
}

function task(over: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    specimen: { id: 'spec-1', display_name: 'Basil the Bold', is_outdoor: true, thumb_url: null },
    task_type: 'water',
    due_at: '2026-10-22T09:00:00Z',
    all_day: true,
    status: 'due',
    satisfied_by: null,
    amount_ml: 450,
    priority: 'normal',
    title: 'Tend Basil the Bold',
    plain_title: 'Water Basil the Bold — 450 ml',
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

describe('which night an alert is about', () => {
  it('tells tonight from a night ahead and a night gone', () => {
    expect(nightWhen(alert({ night_of: ROUND_DATE }), ROUND_DATE)).toBe('tonight');
    expect(nightWhen(alert({ night_of: '2026-10-23' }), ROUND_DATE)).toBe('ahead');
    expect(nightWhen(alert({ night_of: '2026-10-21' }), ROUND_DATE)).toBe('passed');
  });

  it('says so rather than guessing when either date is missing', () => {
    expect(nightWhen(alert(), undefined)).toBe('unknown');
    expect(nightWhen(alert({ night_of: '' }), ROUND_DATE)).toBe('unknown');
  });

  it('does not take `state` for the answer', () => {
    // The frost fixture serves `state: "open"` for a night the scheduler itself
    // refused to raise a task for, the night having gone. An open warning about
    // last Tuesday is not an instruction for this evening.
    const gone = alert({ night_of: '2026-10-21', state: 'open' });
    expect(nightWhen(gone, ROUND_DATE)).toBe('passed');
  });
});

describe('the frost watch, grouped', () => {
  const alerts = [
    alert({ id: 'a-past', night_of: '2026-10-20' }),
    alert({ id: 'a-tonight', night_of: ROUND_DATE }),
    alert({ id: 'a-ahead', night_of: '2026-10-24' }),
  ];

  it('puts tonight first, then what is coming, then what is gone', () => {
    const groups = alertGroups(alerts, ROUND_DATE);
    expect(groups.map((group) => group.when)).toEqual(['tonight', 'ahead', 'passed']);
  });

  it('shows no group for a night nothing is warned about', () => {
    const groups = alertGroups([alert({ night_of: ROUND_DATE })], ROUND_DATE);
    expect(groups).toHaveLength(1);
    expect(groups[0].alerts).toHaveLength(1);
  });

  it('leaves out warnings the engine has already closed', () => {
    const closed = [
      alert({ id: 'r', state: 'resolved' }),
      alert({ id: 'e', state: 'expired' }),
      alert({ id: 'o', state: 'open' }),
    ];
    const groups = alertGroups(closed, ROUND_DATE);
    expect(groups.flatMap((group) => group.alerts).map((a) => a.id)).toEqual(['o']);
  });

  it('pairs a themed heading with a plain one for every group', () => {
    for (const group of alertGroups(alerts, ROUND_DATE)) {
      expect(group.themed).not.toBe(group.plain);
      expect(group.plain.trim()).not.toBe('');
      expect(group.lede.trim()).not.toBe('');
    }
  });
});

describe('what a warning says', () => {
  it('never lets a forecast read as a measurement', () => {
    const said = alertMeasurements(alert());
    expect(said).toMatch(/^Forecast, not a measurement/);
    expect(said).toContain('4 °C');
    expect(said).toContain('11.67 °C');
  });

  it('says plainly that a monitor alert raises no job', () => {
    expect(alertActionPlain(alert({ action: 'monitor' }))).toMatch(/raises no job/);
    expect(alertActionPlain(alert({ action: 'bring_indoors' }))).toMatch(/indoors before dark/);
    expect(alertActionPlain(alert({ action: 'cover' }))).toMatch(/Cover it/);
  });

  it('renders an action this build has never heard of rather than dropping it', () => {
    const said = alertActionPlain(alert({ action: 'swaddle' as never }));
    expect(said).toContain('swaddle');
  });

  it('reads the task id the round filled, and treats a null as an answer', () => {
    expect(alertTaskId(alert())).toBe('task-1');
    // Contract 1.4.1: `GET /almanac/frost` serves null here and always will —
    // the design. Not a bug to work around; a fact about which endpoint knows.
    expect(alertTaskId(alert({ task_id: null }))).toBeNull();
    expect(alertTaskId(alert({ task_id: undefined }))).toBeNull();
  });
});

describe('the frost watch, rendered', () => {
  it('keeps tonight under its own heading, and the rest under theirs', () => {
    const markup = text(
      html(FrostWatch, {
        alerts: [
          alert({ id: 'a', night_of: ROUND_DATE }),
          alert({ id: 'b', night_of: '2026-10-24' }),
        ],
        roundDate: ROUND_DATE,
        taskIdsOnRound: new Set(['task-1']),
      }),
    );
    expect(markup).toContain('The frost watch — Tonight');
    expect(markup).toContain('The frost watch — Nights still to come');
  });

  it('points a warning at the job on the round, where the round filled one', () => {
    const markup = text(
      html(FrostWatch, {
        alerts: [alert()],
        roundDate: ROUND_DATE,
        taskIdsOnRound: new Set(['task-1']),
      }),
    );
    expect(markup).toMatch(/A job for this is on the round above/);
  });

  it('says a job exists elsewhere rather than pointing at nothing', () => {
    const markup = text(
      html(FrostWatch, {
        alerts: [alert()],
        roundDate: ROUND_DATE,
        taskIdsOnRound: new Set<string>(),
      }),
    );
    expect(markup).toMatch(/not on today's round/);
  });

  it('explains a monitor alert instead of implying an unlisted job', () => {
    const markup = text(
      html(FrostWatch, {
        alerts: [alert({ action: 'monitor', task_id: null })],
        roundDate: ROUND_DATE,
      }),
    );
    expect(markup).toMatch(/No job was raised/);
  });

  it('keeps a passed night visible, and says why it is still there', () => {
    const markup = text(
      html(FrostWatch, { alerts: [alert({ night_of: '2026-10-19' })], roundDate: ROUND_DATE }),
    );
    expect(markup).toContain('The frost watch — Nights already gone');
    expect(markup).toMatch(/looks exactly like a warning that was never raised/);
  });

  it('carries each warning’s confidence next to it, never behind a tap', () => {
    const markup = html(FrostWatch, {
      alerts: [
        alert({
          confidence: 'low',
          degraded: true,
          degradations: [
            { code: 'ingest_stale', detail: 'The ingest is a day old.', caps_at: 'low' },
          ],
        }),
      ],
      roundDate: ROUND_DATE,
    });
    expect(markup).not.toContain('<details');
    expect(text(markup)).toContain('The ingest is a day old.');
  });

  it('renders nothing at all when there is nothing open', () => {
    // Svelte's SSR markers survive; what must not is a heading for an empty
    // card, which reads as "the frost watch found nothing" when it was never
    // asked.
    expect(text(html(FrostWatch, { alerts: [], roundDate: ROUND_DATE }))).toBe('');
  });
});

describe('how loudly a job asks', () => {
  it('marks urgent with a word as well as a tone', () => {
    const status = taskUrgency(task({ priority: 'urgent' }));
    expect(status?.plain).toMatch(/Urgent/);
    expect(status?.themed).not.toBe(status?.plain);
  });

  it('marks nothing else, so the marker still means something', () => {
    expect(taskUrgency(task({ priority: 'normal' }))).toBeNull();
    expect(taskUrgency(task({ priority: 'low' }))).toBeNull();
    expect(taskUrgency(task({ priority: undefined }))).toBeNull();
  });

  it('knows whether a round holds one at all', () => {
    expect(hasUrgent([task(), task({ priority: 'urgent' })])).toBe(true);
    expect(hasUrgent([task()])).toBe(false);
  });

  it('gives an urgent row a shape, not only a colour', () => {
    const urgent = html(TaskRow, { task: task({ priority: 'urgent' }), now: new Date() });
    expect(urgent).toMatch(/class="[^"]*\burgent\b/);
    expect(html(TaskRow, { task: task(), now: new Date() })).not.toMatch(/class="[^"]*\burgent\b/);
  });
});
