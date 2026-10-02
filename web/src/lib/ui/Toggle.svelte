<script lang="ts">
  import Label from './Label.svelte';
  import { describedBy } from './ids';

  /** An on/off switch. State is carried by `aria-checked`, by the knob's
   *  position and by the word beside it — never by colour on its own. */
  let {
    checked = $bindable(false),
    themed,
    plain,
    hint,
    disabled = false,
    onPlain = 'On',
    offPlain = 'Off',
    onchange,
  }: {
    checked?: boolean;
    themed?: string;
    plain: string;
    hint?: string;
    disabled?: boolean;
    /** The words shown for each state; both are plain language. */
    onPlain?: string;
    offPlain?: string;
    onchange?: (checked: boolean) => void;
  } = $props();

  const id = $props.id();
  const labelId = `${id}-label`;
  const hintId = $derived(hint ? `${id}-hint` : undefined);
  const describe = $derived(describedBy(hintId));

  function toggle() {
    if (disabled) return;
    checked = !checked;
    onchange?.(checked);
  }
</script>

<div class="toggle">
  <span class="text" id={labelId}>
    <Label {themed} {plain} display="below" where="Toggle" />
    {#if hint}<span class="hint" id={hintId}>{hint}</span>{/if}
  </span>
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-labelledby={labelId}
    aria-describedby={describe}
    {disabled}
    class="switch"
    onclick={toggle}
  >
    <span class="state">{checked ? onPlain : offPlain}</span>
    <span class="track"><span class="knob"></span></span>
  </button>
</div>

<style>
  .toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--moh-space-4);
    min-height: var(--moh-tap);
  }
  .text {
    display: flex;
    flex-direction: column;
  }
  .hint {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .switch {
    display: inline-flex;
    align-items: center;
    gap: var(--moh-space-2);
    min-height: var(--moh-tap);
    padding: var(--moh-space-1) var(--moh-space-2);
    background: none;
    border: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  /* The track dims; the word beside it does not, so "Off" stays readable. */
  .switch:disabled {
    cursor: not-allowed;
  }
  .switch:disabled .track {
    opacity: 0.55;
  }
  .state {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .track {
    position: relative;
    width: 3rem;
    height: 1.75rem;
    border-radius: 999px;
    border: 1px solid var(--moh-border);
    background: var(--moh-surface-sunken);
    transition: background-color var(--moh-motion-quick) var(--moh-motion-ease);
  }
  .knob {
    position: absolute;
    top: 2px;
    inset-inline-start: 2px;
    width: 1.3rem;
    height: 1.3rem;
    border-radius: 50%;
    background: var(--moh-ink-muted);
    transition: transform var(--moh-motion-quick) var(--moh-motion-ease);
  }
  .switch[aria-checked='true'] .track {
    background: var(--moh-accent);
    border-color: var(--moh-accent);
  }
  .switch[aria-checked='true'] .knob {
    background: var(--moh-accent-ink);
    transform: translateX(1.25rem);
  }
</style>
