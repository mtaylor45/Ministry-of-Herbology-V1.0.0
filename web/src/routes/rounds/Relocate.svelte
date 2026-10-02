<script lang="ts">
  /** "Where did it go?" — the one question a completed move has to answer.
   *
   *  A `bring_indoors` task is the only job on this round whose completion
   *  changes a fact about the house, so it is the only one that opens a sheet
   *  instead of ticking straight off. The sheet asks one thing, shows why it is
   *  asking, and carries the scheduler's own caveat about the forecast the whole
   *  instruction rests on — the design, next to the instruction rather than behind
   *  a tooltip, and the design, because nothing here measured the air.
   *
   *  The destination is never pre-filled with a guess. It starts on a remembered
   *  place — somewhere this device watched the same plant leave — or on nothing
   *  at all, and the reader says where it went. An indoor room nobody chose is a
   *  wrong record that outlives the frost, and the register is what next
   *  October's warnings are read from.
   */
  import { Button, Dialog, MemberPicker, SelectField } from '$ui';
  import Caveats from '../shared/Caveats.svelte';
  import type { Location, Member, Task } from './api';
  import {
    WHY_ASK,
    completingWithoutMoving,
    destinationsFor,
    direction,
    locationOptions,
    nowhereToPut,
    relocationPrompt,
    type Suggestion,
  } from './relocation';
  import { taskConfidence } from './tasks';

  let {
    open = $bindable(false),
    task,
    locations,
    suggestion = null,
    members = [],
    memberId = $bindable(''),
    busy = false,
    failure = '',
    oncancel,
    onconfirm,
  }: {
    open?: boolean;
    task: Task;
    locations: readonly Location[];
    /** A place this device watched the plant leave, when there is one. */
    suggestion?: Suggestion | null;
    /** The household, so this completion can say who did it. the design puts that
     *  choice at completion, and for a move this sheet *is* the completion. */
    members?: readonly Member[];
    /** Bound to the same value the batch bar holds, so the two are one choice
     *  shown twice and cannot disagree — and a round of nothing but moves,
     *  which has no batch bar, still has somewhere to make it. */
    memberId?: string;
    busy?: boolean;
    /** Why the last attempt failed. Kept on screen with the sheet open, because
     *  a sheet that closes on failure takes the reader's answer with it. */
    failure?: string;
    oncancel?: () => void;
    onconfirm?: (locationId: string | null) => void;
  } = $props();

  const prompt = $derived(relocationPrompt(task));
  const destinations = $derived(destinationsFor(task, locations));
  const options = $derived(locationOptions(destinations));
  const goingBack = $derived(direction(task) === 'return_outdoors');

  /** The chosen destination. Starts empty unless there is a remembered one, and
   *  an empty choice is a real state: the button that acts on it says plainly
   *  that nothing will be moved. */
  let chosen = $state('');

  // Re-seeded whenever the sheet opens on a different task, so yesterday's
  // answer is never left sitting in the control for today's plant.
  $effect(() => {
    if (open) chosen = suggestion?.locationId ?? '';
  });

  const options_ = $derived([
    { value: '', plain: goingBack ? 'Not saying where' : 'Not saying where it went' },
    ...options,
  ]);
</script>

<Dialog
  bind:open
  themed={prompt.themed}
  plain={prompt.plain}
  description={WHY_ASK}
  closePlain="Close without recording anything"
  onclose={() => oncancel?.()}
>
  <div class="stack">
    {#if failure}
      <p class="failure" role="alert">{failure}</p>
    {/if}

    <!-- The instruction, and how much it is worth, together. The scheduler writes the
         forecast sentence onto `detail`; it is rendered as it stands. -->
    <p class="instruction">{task.plain_title}</p>
    {#if task.detail}
      <p class="detail">{task.detail}</p>
    {/if}
    <Caveats
      payload={task}
      what="This instruction"
      status={taskConfidence(task.confidence)}
      labelAs="text"
      noticeWhenSilent={false}
    />

    {#if destinations.length}
      <SelectField
        bind:value={chosen}
        options={options_}
        themed={goingBack ? 'Set down at' : 'Taken to'}
        plain={goingBack ? 'Where it went back to' : 'Where it was carried to'}
        hint={suggestion
          ? `This device last saw ${task.specimen.display_name} leave ${suggestion.name}, so that is where this starts. Change it if it went somewhere else.`
          : 'The register will be updated to say the plant stands here.'}
        disabled={busy}
      />
      {#if !chosen}
        <p class="consequence">{completingWithoutMoving(task)}</p>
      {/if}
    {:else}
      <p class="nowhere">{nowhereToPut(task)}</p>
      <p class="consequence">{completingWithoutMoving(task)}</p>
    {/if}

    {#if members.length}
      <MemberPicker
        {members}
        bind:value={memberId}
        themed="Done by"
        plain="Who carried it"
        hint="Recorded against this person. The app remembers your last choice on this device."
        disabled={busy}
      />
    {:else}
      <p class="who">
        The household has no members on record, so the ledger will not say who did this. The move is
        recorded either way.
      </p>
    {/if}
  </div>

  {#snippet footer()}
    <div class="acts">
      <Button
        variant="quiet"
        themed="Leave it be"
        plain="Cancel — leave it on the round"
        disabled={busy}
        onclick={() => {
          open = false;
          oncancel?.();
        }}
      />
      <Button
        themed={chosen ? 'Set down and recorded' : 'Done, nothing moved'}
        plain={chosen
          ? 'Mark done and move it in the register'
          : 'Mark done without recording a move'}
        icon="check"
        loading={busy}
        busyPlain="Recording it…"
        onclick={() => onconfirm?.(chosen || null)}
      />
    </div>
  {/snippet}
</Dialog>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-3);
  }
  .instruction {
    margin: 0;
    font-size: var(--moh-text-lg);
  }
  .detail,
  .consequence,
  .nowhere,
  .who {
    margin: 0;
    font-size: var(--moh-text-sm);
  }
  .detail,
  .who {
    color: var(--moh-ink-muted);
  }
  /* The consequence of not naming a place is the one thing on this sheet a
     reader must not skim past, so it is bordered rather than muted. */
  .consequence,
  .nowhere {
    padding: var(--moh-space-3);
    border-inline-start: 4px solid var(--moh-parched);
    background: var(--moh-surface-sunken);
    border-radius: var(--moh-radius);
  }
  .failure {
    margin: 0;
    padding: var(--moh-space-3);
    border: 2px solid var(--moh-ailing);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
  }
  .acts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
    justify-content: flex-end;
  }
</style>
