<script lang="ts">
  /** Tonight's warnings, the ones still coming, and the ones already gone.
   *
   *  This card showed every open alert under one heading — "Frost
   *  warnings tonight and after" — and a reader had to read three dates to work
   *  out which of them was about the evening they were standing in. They are
   *  three different things: a night ahead is a warning, tonight is an
   *  instruction, and a night behind us is a record. `state` does not separate
   *  them, because the frost fixture serves `state: "open"` for a night the
   *  scheduler itself refused to raise a task for, the night having gone.
   *
   *  Each warning names the job it raised, when it raised one. That link is only
   *  possible here: contract 1.4.1 fills `FrostAlert.task_id` on the round's
   *  `alerts` and serves `null` on `GET /almanac/frost`, because the alert is
   *  the weather engine's object and the task is the scheduler's.
   *  A `null` is a real answer — `monitor` never becomes a task, and neither
   *  does a night that has already passed.
   */
  import { Card, Icon, StatusPill, STATUS } from '$ui';
  import Caveats from '../shared/Caveats.svelte';
  import { formatDate } from '../shared/labels';
  import type { FrostAlert } from './api';
  import { alertActionPlain, alertGroups, alertMeasurements, alertTaskId } from './tasks';

  let {
    alerts,
    roundDate,
    /** Ids of the tasks on this round, so a warning only links to a job the
     *  reader can actually see. A task id for a job on another day's round is a
     *  link to nothing. */
    taskIdsOnRound = new Set<string>(),
  }: {
    alerts: readonly FrostAlert[];
    roundDate: string | undefined;
    taskIdsOnRound?: ReadonlySet<string>;
  } = $props();

  const groups = $derived(alertGroups(alerts, roundDate));

  /** A warning that has been answered looks the same as one still owed unless
   *  the pill says which. Tonight's is the guard's own wording; the others say
   *  plainly what they are, because "a killing frost approaches" is wrong for a
   *  night that is behind us. */
  const pillFor = (when: string) => {
    if (when === 'tonight') return STATUS.frostComing;
    if (when === 'ahead')
      return {
        themed: 'A cold night is foretold',
        plain: 'Frost expected on a later night',
        tone: 'frost' as const,
      };
    if (when === 'passed')
      return {
        themed: 'That night has gone',
        plain: 'The night has passed — nothing left to do',
        tone: 'sated' as const,
      };
    return {
      themed: 'No night named',
      plain: 'This warning does not say which night',
      tone: 'parched' as const,
    };
  };
</script>

{#each groups as group (group.when)}
  <Card
    themed={`The frost watch — ${group.themed}`}
    plain={group.plain}
    level={2}
    tone={group.when === 'tonight' ? 'danger' : 'accent'}
  >
    <p class="lede">{group.lede}</p>
    <ul class="alerts">
      {#each group.alerts as alert (alert.id)}
        {@const taskId = alertTaskId(alert)}
        <li>
          <div class="head">
            <a class="title" href={`/specimen/${alert.specimen.id}/tending`}>
              <span class="themed">{alert.specimen.display_name}</span>
              <span class="plain">{alertActionPlain(alert)}</span>
            </a>
            <StatusPill status={pillFor(group.when)} />
          </div>

          <p class="meta">
            {alertMeasurements(alert)}
            {#if alert.advisory}<br />Advisory: {alert.advisory}{/if}
          </p>

          <p class="job">
            <span class="glyph" aria-hidden="true"><Icon name="check" size={16} /></span>
            {#if taskId && taskIdsOnRound.has(taskId)}
              <span
                >A job for this is on the round above — tick it off there, and say where the plant
                went.</span
              >
            {:else if taskId}
              <span
                >A job was raised for this, and it is not on today's round: it belongs to the day it
                has to be done.</span
              >
            {:else if alert.action === 'monitor'}
              <span
                >No job was raised. The guard is watching this one, and a task nobody can perform is
                worse than none.</span
              >
            {:else}
              <span
                >No job is recorded against this warning. It is a thing to watch rather than a thing
                on the list, so nothing will remind you again.</span
              >
            {/if}
          </p>

          <Caveats payload={alert} what="This warning" labelAs="text" noticeWhenSilent={false} />
        </li>
      {/each}
    </ul>
    {#if group.when === 'tonight'}
      <p class="footnote">
        The night of {formatDate(roundDate)} is the one this round is about.
      </p>
    {/if}
  </Card>
{/each}

<style>
  .lede,
  .meta,
  .footnote {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .lede {
    margin-bottom: var(--moh-space-3);
  }
  .footnote {
    margin-top: var(--moh-space-3);
  }
  .alerts {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-3);
  }
  .alerts li {
    display: grid;
    gap: var(--moh-space-2);
    padding: var(--moh-space-3);
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--moh-space-2);
  }
  .title {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .title .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
  }
  .title .plain {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .job {
    display: flex;
    gap: var(--moh-space-2);
    align-items: flex-start;
    margin: 0;
    font-size: var(--moh-text-sm);
  }
  .glyph {
    flex: none;
    margin-top: 2px;
    color: var(--moh-accent);
  }
</style>
