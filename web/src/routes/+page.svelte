<script lang="ts">
  /** Morning Rounds — the home screen, and the one people use daily.
   *
   *  It answers one question: what needs doing to the plants today. Everything
   *  on it is arranged around being read one-handed, outdoors, at 375px, by
   *  somebody already holding a watering can.
   *
   *  Four sections, and the order is the argument:
   *
   *   1. **Needs tending.** Ticked one at a time or in a batch, attributed to a
   *      household member. Each task carries the scheduler's own
   *      certainty next to the instruction.
   *   2. **Already seen to.** Waterings the rain or a sensor settled. Satisfied
   *      is not done, and a task that vanishes because it rained is a task the
   *      reader cannot tell from one that was never scheduled.
   *   3. **Not on the round.** The plants the scheduler could not speak for.
   *   4. **The frost watch.** Tonight's warnings, which are the one thing here
   *      that cannot wait until tomorrow — kept apart from the nights still
   *      coming and the nights already gone, which are not the same thing.
   *
   *  One job on this screen changes a fact about the house rather than
   *  the ledger: `bring_indoors` moves a plant, and the completion has to say
   *  where. That one opens a sheet (`Relocate.svelte`) and never rides in the
   *  batch — `POST /tending/tasks/complete-batch` carries no `new_location_id`,
   *  so a batched move would be ticked off with the plant still in the freeze.
   */
  import { invalidate } from '$app/navigation';
  import {
    Card,
    EmptyState,
    StaleNotice,
    StatusPill,
    nextSelectAll,
    selectionState,
    toggleAll,
    toggleOne,
  } from '$ui';
  import Caveats from './shared/Caveats.svelte';
  import BatchBar from './rounds/BatchBar.svelte';
  import FrostWatch from './rounds/FrostWatch.svelte';
  import Relocate from './rounds/Relocate.svelte';
  import TaskRow from './rounds/TaskRow.svelte';
  import Unscheduled from './rounds/Unscheduled.svelte';
  import { reason, writes, type Location, type Task } from './rounds/api';
  import {
    batchExclusionNotice,
    batchableIds,
    direction,
    forgetOrigin,
    isRelocation,
    locationName,
    readOrigins,
    relocationAnnouncement,
    relocationFailure,
    rememberOrigin,
    suggestedDestination,
    unbatchable,
    type Origins,
  } from './rounds/relocation';
  import { formatDate } from './shared/labels';
  import {
    CERTAINTY_SILENCE,
    SATISFIED_EXPLANATION,
    UNSCHEDULED_SILENCE,
    completableIds,
    completionAnnouncement,
    completionFailure,
    initialMember,
    memberName,
    readRememberedMember,
    rememberMember,
    reportsUnscheduled,
    satisfiedStatus,
    taskConfidence,
    taskMeta,
    tasksReportCertainty,
    unscheduledRows,
  } from './rounds/tasks';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const rounds = $derived(data.rounds.value);
  const due = $derived<Task[]>(rounds?.due ?? []);
  const satisfied = $derived<Task[]>(rounds?.satisfied ?? []);
  const alerts = $derived(rounds?.alerts ?? []);
  const members = $derived(data.members.value ?? []);
  const locations = $derived<Location[]>(data.locations?.value ?? []);
  const register = $derived(data.specimens?.value?.items ?? null);

  /** The tasks the batch bar may act on, and the ones it may not. A move needs
   *  a destination and the batch endpoint has nowhere to carry one. */
  const batchable = $derived(due.filter((task) => !isRelocation(task)));
  const excluded = $derived(unbatchable(due));

  /** Which task ids are on this round, so the frost watch only offers a link to
   *  a job the reader can see from here. */
  const taskIdsOnRound = $derived(new Set(due.map((task) => task.id)));

  /** Fixed once per render pass: every "overdue by" on the screen is measured
   *  from the same instant, so two rows cannot disagree about what day it is. */
  const now = $derived(new Date(rounds?.date ? `${rounds.date}T12:00:00Z` : Date.now()));

  const unscheduled = $derived(unscheduledRows(rounds?.unscheduled ?? [], register));

  let selected = $state(new Set<string>());
  let memberId = $state('');
  let busyBatch = $state(false);
  let busyTask = $state<string | null>(null);
  let announcement = $state('');
  let failure = $state('');

  /** The job whose sheet is open, and what that sheet is told. `origins` is a
   *  per-device memory of where each sheltered plant was standing, read after
   *  mount because it is a browser preference and not server state. */
  let relocating = $state<Task | null>(null);
  let relocateFailure = $state('');
  let origins = $state<Origins>({});

  $effect(() => {
    origins = readOrigins();
  });
  /** Where focus goes when the row that had it has just been ticked off the
   *  round. Without this, completing the last task in a list drops focus to the
   *  top of the document and a screen reader starts the page again. */
  let outcome: HTMLParagraphElement | undefined = $state();

  // the picker defaults to the last member used on this device. It is
  // read after mount because it is a browser preference, not server state.
  $effect(() => {
    if (!memberId && members.length) memberId = initialMember(members, readRememberedMember());
  });

  const checkState = $derived(selectionState(countSelected(), batchable.length));

  function countSelected(): number {
    return batchable.filter((task) => selected.has(task.id)).length;
  }

  function selectAll() {
    const state = selectionState(countSelected(), batchable.length);
    selected = nextSelectAll(state) ? toggleAll(batchableIds(due), state) : new Set<string>();
  }

  async function complete(ids: string[], { batch }: { batch: boolean }) {
    if (!ids.length) return;
    failure = '';
    announcement = '';
    if (batch) busyBatch = true;
    else busyTask = ids[0];
    try {
      const done = await writes.completeBatch(ids, memberId || null, fetch);
      if (memberId) rememberMember(memberId);
      announcement = completionAnnouncement(done.length, memberName(members, memberId));
      selected = new Set<string>();
      await invalidate('moh:rounds');
      outcome?.focus();
    } catch (cause) {
      // The selection is kept deliberately: a reader who has just ticked six
      // rows should not have to find them again to try a second time.
      failure = completionFailure(reason(cause));
    } finally {
      busyBatch = false;
      busyTask = null;
    }
  }

  /** Ticking a row off. A job that moves a plant asks where first; everything
   *  else is a batch of one, so both paths run the same server code. */
  function act(task: Task) {
    failure = '';
    if (!isRelocation(task)) {
      void complete([task.id], { batch: false });
      return;
    }
    relocateFailure = '';
    relocating = task;
  }

  /**
   * A move, confirmed.
   *
   * The origin is worked out *before* the request and only written down after
   * it succeeds: the specimen's location is where the plant is now, and the
   * moment the move goes through, "now" is the room it was carried to. A
   * `return_outdoors` that goes through forgets the origin instead, because a
   * stale one offered next winter looks like knowledge.
   *
   * On failure the sheet stays open with the reason in it. G performs the move
   * before the completion and refuses the whole request if it cannot, so a
   * refusal here means the plant did not move *and* nothing was ticked off —
   * which is what the sentence says, rather than leaving a reader to guess
   * which half happened.
   */
  async function confirmRelocation(locationId: string | null) {
    const task = relocating;
    if (!task) return;
    relocateFailure = '';
    failure = '';
    announcement = '';
    busyTask = task.id;
    const cameFrom = register?.find((row) => row.id === task.specimen.id)?.location?.id ?? null;
    try {
      await writes.complete(
        task.id,
        { completedBy: memberId || null, newLocationId: locationId },
        fetch,
      );
      if (memberId) rememberMember(memberId);
      if (locationId) {
        if (direction(task) === 'bring_indoors') rememberOrigin(task.specimen.id, cameFrom);
        else forgetOrigin(task.specimen.id);
        origins = readOrigins();
      }
      announcement = relocationAnnouncement(
        task,
        locationId ? locationName(locations, locationId) : null,
        memberName(members, memberId),
      );
      relocating = null;
      // The batch selection is *not* cleared. A move is completed on its own
      // row and was never in it, so throwing away six ticks somebody made
      // before carrying a plant inside would be losing their work to do it.
      await invalidate('moh:rounds');
      outcome?.focus();
    } catch (cause) {
      relocateFailure = relocationFailure(reason(cause));
    } finally {
      busyTask = null;
    }
  }
</script>

<svelte:head><title>Morning Rounds — The Ministry of Herbology</title></svelte:head>

<h1>
  <span class="themed">Morning Rounds</span>
  <span class="plain">What needs doing today{rounds ? ` — ${formatDate(rounds.date)}` : ''}</span>
</h1>

{#if data.rounds.error}
  <StaleNotice plain="Today's round" asOf={null} reason={data.rounds.error} />
  <p class="nothing">
    Nothing on this screen is a statement about your plants right now — the round could not be read
    at all. Nothing has been watered, and nothing has been ruled out.
  </p>
{:else}
  {#if rounds?.greeting}
    <p class="greeting">{rounds.greeting}</p>
  {/if}

  <div class="stack">
    <!-- One live region for the whole screen: both ways of completing a task
         report through it, so "3 tasks marked done" is announced once however
         it was done. -->
    <p class="announce" role="status" aria-live="polite" tabindex="-1" bind:this={outcome}>
      {announcement}
    </p>
    {#if failure}
      <p class="failure" role="alert">{failure}</p>
    {/if}

    <Card themed="What is owed" plain="Needs tending — due today" level={2}>
      {#if due.length}
        {#if !tasksReportCertainty(due)}
          <p class="silence">{CERTAINTY_SILENCE}</p>
        {/if}

        <!-- No bar on a round the batch cannot act on at all. "Nothing selected
             of 0" above a disabled tick and a dead button is furniture, and it
             is furniture nailed to the top of a phone screen. -->
        {#if batchable.length}
          <BatchBar
            total={batchable.length}
            selected={countSelected()}
            {checkState}
            {members}
            bind:memberId
            busy={busyBatch}
            excluded={excluded.length > 0}
            onselectall={selectAll}
            oncomplete={() => complete(completableIds(due, selected), { batch: true })}
          />
        {/if}

        <!-- Below the bar rather than inside it: the bar is sticky and stands
             327px tall at 375px even after this was taken out of it. This is an
             explanation, not a control, and it belongs where the reader meets
             the discrepancy — between the button's count and the longer list
             under it. -->
        {#if excluded.length}
          <p class="excluded">{batchExclusionNotice(excluded)}</p>
        {/if}

        <ul class="tasks">
          {#each due as task (task.id)}
            <li>
              <TaskRow
                {task}
                {now}
                selected={selected.has(task.id)}
                busy={busyTask === task.id}
                disabled={busyBatch || (busyTask !== null && busyTask !== task.id)}
                onselect={() => (selected = toggleOne(selected, task.id))}
                oncomplete={() => act(task)}
              />
            </li>
          {/each}
        </ul>
      {:else}
        <EmptyState
          icon="check"
          themed="The grounds are content"
          plain="Nothing is due today"
          body="Nothing is outstanding, which means the round is done rather than that the house is unaccounted for: waterings something else settled, and plants nothing is scheduled for, each get a section of their own whenever there are any."
        />
      {/if}
    </Card>

    {#if satisfied.length}
      <Card themed="Already seen to" plain="Settled without you — not done, not owed" level={2}>
        <p class="lede">{SATISFIED_EXPLANATION}</p>
        <ul class="settled">
          {#each satisfied as task (task.id)}
            <li>
              <div class="head">
                <span class="title">
                  <span class="themed">{task.title}</span>
                  <span class="plain">{task.plain_title}</span>
                </span>
                <StatusPill status={satisfiedStatus(task)} />
              </div>
              <p class="meta">{taskMeta(task, now)}</p>
              <Caveats
                payload={task}
                what="This reckoning"
                status={taskConfidence(task.confidence)}
                labelAs="text"
                noticeWhenSilent={false}
              />
              <a class="open" href={task.deep_link}>Open {task.specimen.display_name}</a>
            </li>
          {/each}
        </ul>
      </Card>
    {/if}

    {#if unscheduled.length}
      <Unscheduled rows={unscheduled} />
    {:else if !reportsUnscheduled(rounds)}
      <Card themed="Not on the round" plain="Plants nothing is scheduled for" level={2}>
        <p class="silence">{UNSCHEDULED_SILENCE}</p>
      </Card>
    {/if}

    <FrostWatch {alerts} roundDate={rounds?.date} {taskIdsOnRound} />

    {#if data.members.error}
      <p class="aside">
        The household roster could not be read ({data.members.error}) — tasks can still be marked
        done, but there is nobody to attribute them to until it can.
      </p>
    {/if}
    {#if data.specimens?.error && unscheduled.length}
      <p class="aside">
        The register could not be read ({data.specimens.error}), so the plants above are named by
        their register entry rather than by name.
      </p>
    {/if}
    {#if data.locations?.error}
      <p class="aside">
        The list of places could not be read ({data.locations.error}), so a job that moves a plant
        cannot offer anywhere to move it to. It can still be marked done — the register will go on
        saying the plant is where it was.
      </p>
    {/if}
  </div>
{/if}

{#if relocating}
  <Relocate
    open={true}
    task={relocating}
    {locations}
    suggestion={suggestedDestination(relocating, locations, origins)}
    {members}
    bind:memberId
    busy={busyTask === relocating.id}
    failure={relocateFailure}
    oncancel={() => {
      relocating = null;
      relocateFailure = '';
    }}
    onconfirm={(locationId) => confirmRelocation(locationId)}
  />
{/if}

<style>
  h1 {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin-bottom: var(--moh-space-3);
  }
  h1 .themed {
    font-family: var(--moh-font-display);
  }
  .plain {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .greeting {
    margin: 0 0 var(--moh-space-4);
    font-style: italic;
    color: var(--moh-ink-muted);
  }
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }
  .announce:empty {
    display: none;
  }
  .announce {
    margin: 0;
    padding: var(--moh-space-3);
    border-inline-start: 4px solid var(--moh-thriving);
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
  /* A row scrolled to by the browser — a focus move, a fragment link, an
     assistive-technology jump — lands under the sticky bar above it unless it
     asks for the room. The bar's own height is the margin it needs. */
  .tasks li {
    scroll-margin-top: var(--moh-space-12);
  }
  .excluded,
  .nothing,
  .lede,
  .silence {
    margin: 0 0 var(--moh-space-3);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .silence {
    padding: var(--moh-space-3);
    border: 1px dashed var(--moh-border);
    border-radius: var(--moh-radius);
  }
  .tasks,
  .settled {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-3);
  }
  .settled li {
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
  .meta {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .open {
    display: inline-flex;
    align-items: center;
    min-height: var(--moh-tap);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .aside {
    margin: var(--moh-space-4) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  /* The whole page sits above the fixed section bar on a phone. */
  ul:last-child {
    margin-bottom: 0;
  }
</style>
