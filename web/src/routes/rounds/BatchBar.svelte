<script lang="ts">
  /** Select the round, say who did it, tick it all off.
   *
   *  Three controls in a fixed order — select all, who, do it — so the tab
   *  order matches the sentence. The bar sticks to the top of the list rather
   *  than the bottom of the screen: the section bar is already fixed down
   *  there, and a phone with two bars fighting for the same forty-four pixels
   *  is a phone that mis-taps.
   *
   *  The count is a word, never a colour: "3 of 9 selected" is the state, and
   *  the button says what it will do with them.
   *
   *  `excluded` says *whether* the round holds a job this bar cannot complete —
   *  it changes the select-all's own wording, which is a claim this control
   *  makes and has to keep true. The sentence explaining it is rendered by the
   *  page, below this bar, and deliberately not inside it: the bar is sticky,
   *  and at 375px it already stands 422px tall against an 800px viewport. Four
   *  more lines of prose nailed to the top of the screen is four more lines of
   *  the list nobody can reach.
   */
  import { Button, MemberPicker, TaskCheckbox, selectionSummary } from '$ui';
  import type { CheckState } from '$ui';
  import type { Member } from './api';
  import { batchButtonPlain } from './tasks';

  let {
    total,
    selected,
    checkState,
    members,
    memberId = $bindable(''),
    busy = false,
    excluded = false,
    onselectall,
    oncomplete,
  }: {
    /** How many tasks this bar can actually complete — not how many are on the
     *  round. A job that moves a plant is not one of them. */
    total: number;
    selected: number;
    checkState: CheckState;
    members: Member[];
    memberId?: string;
    busy?: boolean;
    /** Whether the round holds a job this bar cannot complete. The bar only
     *  needs to know *that*, to word its select-all honestly; the page says
     *  why, underneath. */
    excluded?: boolean;
    onselectall?: () => void;
    oncomplete?: () => void;
  } = $props();

  const summary = $derived(selectionSummary(selected, total));
</script>

<div class="bar">
  <div class="pick">
    <!-- "Every task due" stopped being true the day a job that moves a plant
         came onto the round: the select-all reaches the six it can complete,
         not the nine that are owed, and a control that claims the larger number
         is a control that quietly loses three. -->
    <TaskCheckbox
      {checkState}
      themed="The whole round"
      plain={excluded ? 'Select every task the batch can complete' : 'Select every task due'}
      meta={summary}
      meaning="selection"
      disabled={busy || total === 0}
      donePlain="All selected"
      onchange={() => onselectall?.()}
    />
  </div>

  <div class="who">
    {#if members.length}
      <MemberPicker
        {members}
        bind:value={memberId}
        themed="Done by"
        plain="Who did these"
        hint="Recorded against this person. The app remembers your last choice on this device."
        disabled={busy}
      />
    {:else}
      <p class="nobody">
        The household has no members on record, so nothing can be attributed. These tasks can still
        be marked done; the ledger will simply not say who did them.
      </p>
    {/if}
  </div>

  <!-- The themed half is back. It was dropped in #26 because `Label` painted
       the plain half `--moh-ink-muted`, which on a filled primary button's
       `--moh-accent` ground measured 1.26:1 — a WCAG AA failure at any size,
       and the original-theme rule broken twice over since the unreadable half was the one
       carrying the meaning. The design system's `--moh-plain-ink` gives a
       filled control its own ink, and the pairing now measures 10.91:1 themed
       and 10.42:1 plain on parchment, 6.68:1 and 6.65:1 on greenhouse. -->
  <Button
    themed="See to the lot"
    plain={batchButtonPlain(selected)}
    icon="check"
    full
    loading={busy}
    disabled={selected === 0}
    busyPlain="Marking them done…"
    onclick={() => oncomplete?.()}
  />
</div>

<style>
  .bar {
    position: sticky;
    top: 0;
    z-index: 5;
    display: grid;
    gap: var(--moh-space-3);
    margin-bottom: var(--moh-space-3);
    padding: var(--moh-space-3);
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
  }
  .nobody {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  /* From a tablet up there is room for the picker beside the selection. */
  @media (min-width: 600px) {
    .bar {
      grid-template-columns: 1fr auto;
      align-items: end;
    }
    .pick {
      grid-column: 1 / -1;
    }
  }
</style>
