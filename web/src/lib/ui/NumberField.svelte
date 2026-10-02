<script lang="ts">
  import Field from './Field.svelte';

  /** A number with its unit stated in the label or suffix. Units are SI
   *  internally (mm, °C, litres); the suffix is what the reader sees. */
  let {
    value = $bindable<number | null>(null),
    themed,
    plain,
    hint,
    error,
    suffix,
    min,
    max,
    step = 1,
    required = false,
    disabled = false,
    name,
    oninput,
  }: {
    value?: number | null;
    themed?: string;
    plain: string;
    hint?: string;
    error?: string;
    /** "mm", "°C", "litres" — rendered beside the control and read aloud. */
    suffix?: string;
    min?: number;
    max?: number;
    step?: number | 'any';
    required?: boolean;
    disabled?: boolean;
    name?: string;
    oninput?: (event: Event) => void;
  } = $props();

  const id = $props.id();
  const suffixId = $derived(suffix ? `${id}-suffix` : undefined);
</script>

<Field {id} {themed} {plain} {hint} {error} {required}>
  {#snippet children({ describedBy, invalid })}
    <div class="wrap">
      <input
        {id}
        class="control"
        type="number"
        inputmode="decimal"
        {name}
        {min}
        {max}
        {step}
        {disabled}
        {oninput}
        aria-describedby={[suffixId, describedBy].filter(Boolean).join(' ') || undefined}
        aria-invalid={invalid ? 'true' : undefined}
        aria-required={required ? 'true' : undefined}
        bind:value
      />
      {#if suffix}<span class="suffix" id={suffixId}>{suffix}</span>{/if}
    </div>
  {/snippet}
</Field>

<style>
  .wrap {
    display: flex;
    align-items: stretch;
    gap: var(--moh-space-2);
  }
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
  .control[aria-invalid='true'] {
    border-color: var(--moh-danger);
    border-width: 2px;
  }
  .control:disabled {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
  }
  .suffix {
    display: inline-flex;
    align-items: center;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
    white-space: nowrap;
  }
</style>
