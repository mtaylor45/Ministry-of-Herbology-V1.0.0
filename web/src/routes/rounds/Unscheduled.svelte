<script lang="ts">
  /** The plants this round could not speak for.
   *
   *  the design, written about the frost guard and true word for word here: a
   *  list of tasks cannot say *"and these three I could not judge"*. A plant
   *  with no watering interval anywhere — no cited care value, no species
   *  column, no household rule — generates no task, and a plant with no task is
   *  indistinguishable on this screen from a plant that needs nothing.
   *
   *  So each one is named with the scheduler's own reason, and each links to
   *  the facet where a care value can be set. Without this the round is a list
   *  of what happened to be schedulable, quietly presented as the whole house.
   */
  import { Card, Icon } from '$ui';
  import type { UnscheduledRow } from './tasks';

  let { rows }: { rows: UnscheduledRow[] } = $props();
</script>

<Card themed="Not on the round" plain="Plants nothing is scheduled for" level={2} tone="accent">
  <p class="lede">
    {rows.length === 1 ? 'One plant is' : `${rows.length} plants are`} in the register with nothing scheduled
    for {rows.length === 1 ? 'it' : 'them'} today. That is not the same as needing nothing.
  </p>
  <ul>
    {#each rows as row (row.specimenId + row.reason)}
      <li>
        <span class="glyph" aria-hidden="true"><Icon name="warning" size={18} /></span>
        <span class="says">
          <a class="name" href={row.href}>{row.name}</a>
          {#if !row.named}
            <span class="id">Register entry {row.specimenId}</span>
          {/if}
          <span class="reason">{row.reason}</span>
        </span>
      </li>
    {/each}
  </ul>
</Card>

<style>
  .lede {
    margin: 0 0 var(--moh-space-3);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-3);
  }
  li {
    display: flex;
    gap: var(--moh-space-2);
    align-items: flex-start;
  }
  .glyph {
    flex: none;
    margin-top: 2px;
    color: var(--moh-parched);
  }
  .says {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    min-width: 0;
  }
  .name {
    display: inline-flex;
    align-items: center;
    min-height: var(--moh-tap);
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
  }
  .id {
    font-size: var(--moh-text-xs);
    color: var(--moh-ink-muted);
    word-break: break-all;
  }
  .reason {
    font-size: var(--moh-text-sm);
  }
</style>
