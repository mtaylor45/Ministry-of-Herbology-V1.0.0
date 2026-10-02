<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import { describedBy } from './ids';

  /** Label, hint and error plumbing shared by every field primitive.
   *
   *  The control is a snippet so each field keeps its own native element, and
   *  gets back the ids it must point `aria-describedby` at. */
  let {
    id,
    themed,
    plain,
    hint,
    error,
    required = false,
    children,
  }: {
    id: string;
    themed?: string;
    plain: string;
    hint?: string;
    error?: string;
    required?: boolean;
    children: Snippet<[{ describedBy: string | undefined; invalid: boolean }]>;
  } = $props();

  const hintId = $derived(hint ? `${id}-hint` : undefined);
  const errorId = $derived(error ? `${id}-error` : undefined);
  const describe = $derived(describedBy(hintId, errorId));
</script>

<div class="field" class:invalid={Boolean(error)}>
  <label class="label" for={id}>
    <Label {themed} {plain} where="Field" />
    {#if required}
      <span class="required" aria-hidden="true">*</span><span class="visually-hidden">
        (required)</span
      >
    {/if}
  </label>
  {@render children({ describedBy: describe, invalid: Boolean(error) })}
  {#if hint}<p class="hint" id={hintId}>{hint}</p>{/if}
  {#if error}
    <p class="error" id={errorId}>
      <Icon name="warning" size={16} />
      <span class="visually-hidden">Error: </span>{error}
    </p>
  {/if}
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
  }
  /* §3 puts form labels, hints and system messages in the utility sans. The
     themed half of the label keeps the display serif — Label decides that. */
  .label {
    display: inline-flex;
    align-items: baseline;
    gap: var(--moh-space-1);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .required {
    color: var(--moh-danger);
  }
  .hint {
    margin: 0;
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  /* The error is marked by an icon and the word "Error", not by red alone. */
  .error {
    display: flex;
    align-items: center;
    gap: var(--moh-space-1);
    margin: 0;
    color: var(--moh-danger);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
</style>
