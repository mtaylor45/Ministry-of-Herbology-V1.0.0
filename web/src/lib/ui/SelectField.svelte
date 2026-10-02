<script lang="ts">
  import Field from './Field.svelte';
  import Icon from './Icon.svelte';
  import type { SelectOption } from './types';

  /** A native select — it is the control that works best one-handed, outdoors,
   *  in gloves, and it is the one every platform already knows how to show. */
  let {
    value = $bindable(''),
    options,
    themed,
    plain,
    hint,
    error,
    required = false,
    disabled = false,
    name,
    onchange,
  }: {
    value?: string;
    options: SelectOption[];
    themed?: string;
    plain: string;
    hint?: string;
    error?: string;
    required?: boolean;
    disabled?: boolean;
    name?: string;
    onchange?: (event: Event) => void;
  } = $props();

  const id = $props.id();

  /** Option text: plain first, themed in brackets — an option list is read
   *  aloud one item at a time, so the meaning has to come first. */
  const optionText = (option: SelectOption) =>
    option.themed ? `${option.plain} (${option.themed})` : option.plain;
</script>

<Field {id} {themed} {plain} {hint} {error} {required}>
  {#snippet children({ describedBy, invalid })}
    <div class="wrap">
      <select
        {id}
        class="control"
        {name}
        {disabled}
        {onchange}
        aria-describedby={describedBy}
        aria-invalid={invalid ? 'true' : undefined}
        aria-required={required ? 'true' : undefined}
        bind:value
      >
        {#each options as option (option.value)}
          <option value={option.value} disabled={option.disabled}>{optionText(option)}</option>
        {/each}
      </select>
      <span class="chevron" aria-hidden="true"><Icon name="chevronDown" size={18} /></span>
    </div>
  {/snippet}
</Field>

<style>
  .wrap {
    position: relative;
    display: flex;
  }
  .control {
    appearance: none;
    width: 100%;
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-8) var(--moh-space-2) var(--moh-space-3);
    background: var(--moh-field);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-base);
  }
  .control[aria-invalid='true'] {
    border-color: var(--moh-danger);
    border-width: 2px;
  }
  .control:disabled {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
  }
  .chevron {
    position: absolute;
    inset-block: 0;
    inset-inline-end: var(--moh-space-3);
    display: flex;
    align-items: center;
    color: var(--moh-ink-muted);
    pointer-events: none;
  }
</style>
