<script lang="ts">
  import Label from './Label.svelte';
  import { describedBy } from './ids';
  import { CHECKED_PLAIN, type CheckMeaning, type CheckState } from './selection';

  /** The most-used control in the app: completing a task, one tap or a batch
   *  at a time.
   *
   *  The whole row is the target and it is never smaller than 44px, because it
   *  is tapped outdoors, one-handed, in gloves. State is carried by the tick's
   *  shape and by a word, not by colour. `state="mixed"` is the select-all
   *  control for a partly selected list.
   *
   *  `meaning` says what a tick *is*. Completion is the default: the row is
   *  struck through and says "Done". Selection is for a list where the tick
   *  gathers rows for a batch and the completion happens elsewhere — Morning
   *  Rounds, where attribution is chosen at completion, so a tick
   *  cannot be the completion. A selected row says "Selected" and is *not*
   *  struck through, because struck-through text reads as finished whatever the
   *  word beside it says. The app's screens asked for this in the earlier review after working around
   *  it from outside with `donePlain` and finding the strike-through unreachable. */
  let {
    checked = $bindable(false),
    checkState,
    meaning = 'completion',
    themed,
    plain,
    meta,
    disabled = false,
    name,
    value,
    donePlain,
    onchange,
  }: {
    checked?: boolean;
    /** Overrides `checked`; `mixed` is the batch select-all state. */
    checkState?: CheckState;
    /** What a tick means here. `selection` drops the strike-through. */
    meaning?: CheckMeaning;
    themed?: string;
    plain: string;
    /** Plain secondary line: "Water — due today". */
    meta?: string;
    disabled?: boolean;
    name?: string;
    value?: string;
    /** Overrides the word shown once it is ticked. Never colour alone. The
     *  default follows `meaning` — "Done" or "Selected" — so passing this is
     *  only for a list that needs its own wording. */
    donePlain?: string;
    onchange?: (checked: boolean) => void;
  } = $props();

  const id = $props.id();
  const metaId = $derived(meta ? `${id}-meta` : undefined);
  const describe = $derived(describedBy(metaId));
  const current = $derived<CheckState>(checkState ?? (checked ? 'checked' : 'unchecked'));
  const tickedPlain = $derived(donePlain?.trim() || CHECKED_PLAIN[meaning]);

  let input: HTMLInputElement | undefined = $state();

  // `indeterminate` is a property, not an attribute; the server renders
  // data-state="mixed" and aria-checked="mixed" so the state is not lost.
  $effect(() => {
    if (input) input.indeterminate = current === 'mixed';
  });

  // True only for the tap that completed the task, so the settle below plays
  // for an act and never for a row that arrived on the page already done.
  let settling = $state(false);

  function handle(event: Event) {
    const next = (event.currentTarget as HTMLInputElement).checked;
    checked = next;
    settling = next && meaning === 'completion';
    onchange?.(next);
  }
</script>

<label
  class="task"
  data-state={current}
  data-meaning={meaning}
  data-settling={settling || undefined}
  class:disabled
>
  <input
    bind:this={input}
    {id}
    class="input"
    type="checkbox"
    {name}
    {value}
    {disabled}
    checked={current === 'checked'}
    aria-checked={current === 'mixed' ? 'mixed' : undefined}
    aria-describedby={describe}
    onchange={handle}
  />
  <span class="box" aria-hidden="true">
    {#if current === 'mixed'}
      <svg viewBox="0 0 24 24" class="tick" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M6 12h12" stroke-linecap="round" />
      </svg>
    {:else}
      <!-- A quill stroke rather than a machine tick; it draws itself on completion. -->
      <svg viewBox="0 0 24 24" class="tick" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M4 13l5 5L20 6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    {/if}
  </span>
  <span class="text">
    <Label {themed} {plain} display="below" where="TaskCheckbox" />
    {#if meta}<span class="meta" id={metaId}>{meta}</span>{/if}
  </span>
  {#if current === 'checked'}<span class="done">{tickedPlain}</span>{/if}
</label>

<style>
  .task {
    display: flex;
    align-items: center;
    gap: var(--moh-space-3);
    /* the entire row is the tap target */
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    border-radius: var(--moh-radius);
    cursor: pointer;
  }
  /* Only the box dims. The words stay in the muted ink, because a task that
     cannot be ticked is still a task someone has to read. */
  .task.disabled {
    color: var(--moh-ink-muted);
    cursor: not-allowed;
  }
  .task.disabled .box {
    opacity: 0.55;
  }
  .task[data-state='checked'] {
    background: var(--moh-selected);
  }

  .input {
    position: absolute;
    width: var(--moh-tap);
    height: var(--moh-tap);
    margin: 0;
    opacity: 0;
    cursor: inherit;
  }

  .box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 28px;
    height: 28px;
    border: 2px solid var(--moh-gold-line);
    border-radius: var(--moh-radius);
    background: var(--moh-field);
    color: var(--moh-accent-ink);
  }
  .task[data-state='checked'] .box,
  .task[data-state='mixed'] .box {
    background: var(--moh-accent);
    border-color: var(--moh-accent);
  }

  /* The focus ring belongs to the visible box, not to the hidden input. */
  .input:focus-visible + .box {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }

  .tick {
    width: 20px;
    height: 20px;
    stroke-dasharray: 30;
    stroke-dashoffset: 30;
  }
  .task[data-state='checked'] .tick,
  .task[data-state='mixed'] .tick {
    stroke-dashoffset: 0;
  }
  /* Whimsy at a moment: a tick that completes something is written rather than
     switched on. A tick that only gathers a row for a batch is not a moment —
     it appears at once, because six of them in a row would be six ceremonies. */
  .task[data-meaning='completion'] .tick {
    transition: stroke-dashoffset var(--moh-motion-sheet) var(--moh-motion-ease);
  }
  /* And the row settles: it takes its filled ground and comes to rest a hair
     lower, the way a ledger line dries. Once, for the tap that did it. The
     sheet token, like the tick; reduced motion clamps it in tokens.css. */
  .task[data-settling='true'] {
    animation: settle var(--moh-motion-sheet) var(--moh-motion-ease);
  }
  @keyframes settle {
    from {
      transform: translateY(-3px);
      background-color: transparent;
    }
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  /* Metadata gets §3's utility sans. Not its uppercase or its wide tracking:
     those are for a word or two on a tab, and this line is a sentence with a
     date in it. §25 outranks §3 where the two disagree. */
  .meta {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .done {
    flex: none;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-thriving);
  }
  /* "Selected" is a neutral fact about this row, not a green verdict on it. */
  .task[data-meaning='selection'] .done {
    color: var(--moh-ink-muted);
  }
  /* Struck through only when the tick is the completion. In a selection list
     the row is still to be done, and struck-through text reads as finished
     however the word beside it is worded. */
  .task[data-meaning='completion'][data-state='checked'] .text {
    text-decoration: line-through;
    text-decoration-color: var(--moh-ink-muted);
  }
</style>
