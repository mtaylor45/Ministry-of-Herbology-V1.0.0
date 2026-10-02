<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import Field from './Field.svelte';

  /** Single-line text, or a multi-line note when `rows` is given. */
  let {
    value = $bindable(''),
    themed,
    plain,
    hint,
    error,
    required = false,
    disabled = false,
    readonly = false,
    placeholder,
    name,
    autocomplete,
    rows,
    maxlength,
    oninput,
  }: {
    value?: string;
    themed?: string;
    plain: string;
    hint?: string;
    error?: string;
    required?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    placeholder?: string;
    name?: string;
    autocomplete?: HTMLInputAttributes['autocomplete'];
    /** Given, the field becomes a textarea of this many rows. */
    rows?: number;
    maxlength?: number;
    oninput?: (event: Event) => void;
  } = $props();

  const id = $props.id();
</script>

<Field {id} {themed} {plain} {hint} {error} {required}>
  {#snippet children({ describedBy, invalid })}
    {#if rows}
      <textarea
        {id}
        class="control"
        {name}
        {rows}
        {placeholder}
        {disabled}
        {readonly}
        {maxlength}
        {oninput}
        aria-describedby={describedBy}
        aria-invalid={invalid ? 'true' : undefined}
        aria-required={required ? 'true' : undefined}
        bind:value
      ></textarea>
    {:else}
      <input
        {id}
        class="control"
        type="text"
        {name}
        {placeholder}
        {disabled}
        {readonly}
        {maxlength}
        {autocomplete}
        {oninput}
        aria-describedby={describedBy}
        aria-invalid={invalid ? 'true' : undefined}
        aria-required={required ? 'true' : undefined}
        bind:value
      />
    {/if}
  {/snippet}
</Field>

<style>
  .control {
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    background: var(--moh-field);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-base);
    width: 100%;
  }
  .control::placeholder {
    color: var(--moh-ink-muted);
  }
  .control[aria-invalid='true'] {
    border-color: var(--moh-danger);
    border-width: 2px;
  }
  /* A disabled field's value is still information: muted ink on the sunken
     surface, not a dimmed field. */
  .control:disabled {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
  }
</style>
