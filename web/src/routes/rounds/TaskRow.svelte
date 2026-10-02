<script lang="ts">
  /** One job on the round: what it is, how sure the scheduler is about it, and
   *  the way to tick it off.
   *
   *  Most rows carry a checkbox and a button, because both are how this screen
   *  is used — six plants watered in a row on a Saturday, one watered on the way
   *  out of the door on a Tuesday. A row that *moves a plant* carries only the
   *  button: its completion has to say where the plant went, and the batch
   *  endpoint has nowhere to carry that (`relocation.ts`). Rather than offer a
   *  tick that would quietly mark a plant sheltered while it stands in a freeze,
   *  the row says why there is no tick.
   *
   *  The caveat is inside the row, under the instruction, never behind a tap.
   *  A task worked out from an uncited interval or a degraded water balance has
   *  to look different from one measured for the species, and
   *  there is no soil probe anywhere in this house to catch it if it does not.
   */
  import { Button, StatusPill, TaskCheckbox } from '$ui';
  import Caveats from '../shared/Caveats.svelte';
  import type { Task } from './api';
  import { isRelocation } from './relocation';
  import { instructionNote, taskConfidence, taskMeta, taskUrgency } from './tasks';

  let {
    task,
    now,
    selected = false,
    busy = false,
    disabled = false,
    onselect,
    oncomplete,
  }: {
    task: Task;
    now: Date;
    selected?: boolean;
    /** This row's own completion is in flight. */
    busy?: boolean;
    disabled?: boolean;
    onselect?: (checked: boolean) => void;
    /** For a relocation this opens the sheet that asks where; for anything else
     *  it completes the task on the spot. */
    oncomplete?: () => void;
  } = $props();

  const note = $derived(instructionNote(task));
  const moves = $derived(isRelocation(task));
  const urgency = $derived(taskUrgency(task));
  const meta = $derived(taskMeta(task, now));
</script>

<div class="task" class:urgent={task.priority === 'urgent'} class:moves>
  {#if urgency}
    <!-- Shape and a word, not a colour: the row also takes a heavier rule down
         its leading edge, and the pill says "urgent" in as many letters. -->
    <p class="flag"><StatusPill status={urgency} /></p>
  {/if}

  {#if moves}
    <div class="named">
      <span class="themed">{task.title}</span>
      <span class="plain">{task.plain_title}</span>
      <span class="meta">{meta}</span>
    </div>
  {:else}
    <TaskCheckbox
      themed={task.title}
      plain={task.plain_title}
      {meta}
      meaning="selection"
      checked={selected}
      disabled={disabled || busy}
      name="task"
      value={task.id}
      onchange={(checked) => onselect?.(checked)}
    />
  {/if}

  <!-- The caveat sits between the instruction and the button that acts on it,
       which is the only place a reader in a hurry cannot miss it. -->
  <Caveats
    payload={task}
    what="This instruction"
    status={taskConfidence(task.confidence)}
    labelAs="text"
    noticeWhenSilent={false}
  />
  {#if note}
    <p class="note">{note}</p>
  {/if}

  {#if moves}
    <p class="why-no-tick">
      Not part of the batch below: completing this has to say where the plant went, and only the
      button on this row can ask.
    </p>
  {/if}

  <div class="acts">
    <a class="open" href={task.deep_link}>
      Open {task.specimen.display_name}
      <span class="visually-hidden">— its tending facet, where its care values are edited</span>
    </a>
    <!-- The visible label is short enough to read on a phone; the accessible
         name says which plant, because eight buttons all called "Mark done"
         are eight identical buttons to anybody listening to the page. The
         ellipsis on a move is not decoration: that button opens a question. -->
    <Button
      variant={moves ? 'primary' : 'quiet'}
      icon="check"
      themed={moves ? 'See it settled' : 'Done and dusted'}
      plain={moves ? 'Mark done — say where' : 'Mark done'}
      aria-label={moves
        ? `See it settled — mark done and say where it went: ${task.plain_title}`
        : `Done and dusted — mark done: ${task.plain_title}`}
      loading={busy}
      disabled={disabled && !busy}
      busyPlain="Marking it done…"
      onclick={() => oncomplete?.()}
    />
  </div>
</div>

<style>
  .task {
    display: grid;
    gap: var(--moh-space-2);
    padding: var(--moh-space-3);
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
  }
  /* A job with a sunset for a deadline does not look like a watering. The rule
     is a shape, and the pill above carries the word — neither is a colour on
     its own. */
  .task.urgent {
    border-inline-start: 6px solid var(--moh-frost);
    padding-inline-start: calc(var(--moh-space-3) - 5px);
  }
  .flag {
    margin: 0;
  }
  /* A relocation row has no checkbox, so it lays its own label out the way
     `TaskCheckbox` would: themed above, plain below, metadata under both. */
  .named {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding: var(--moh-space-2) var(--moh-space-3);
  }
  .named .themed {
    font-family: var(--moh-font-display);
    font-size: 1.08em;
    font-weight: 500;
  }
  .named .plain {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-plain-ink, var(--moh-ink-muted));
  }
  .named .meta,
  .why-no-tick {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .why-no-tick {
    margin: 0;
    padding-inline: var(--moh-space-3);
  }
  .note {
    margin: 0;
    padding: var(--moh-space-3);
    border-inline-start: 4px solid var(--moh-parched);
    background: var(--moh-surface-sunken);
    border-radius: var(--moh-radius);
    font-size: var(--moh-text-sm);
  }
  .acts {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--moh-space-2);
  }
  .open {
    display: inline-flex;
    align-items: center;
    min-height: var(--moh-tap);
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
</style>
