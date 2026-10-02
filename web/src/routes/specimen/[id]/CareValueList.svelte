<script lang="ts">
  /** Care values, each with its source, its confidence, and a way to correct it.
   *
   *  the source and the confidence sit next to the value, not behind
   *  a tap, and every value is editable. a value with no citation is
   *  the dangerous case, not the tidy one — an uncited `water_k_c` is the only
   *  thing standing between an outdoor plant and the wrong amount of water, so
   *  it is called out above the list as well as inside it.
   */
  import { Button, Dialog, NumberField, StatusPill, TextField, Toggle } from '$ui';
  import type { CareValue } from './api';
  import { reason, saveCareValue } from './api';
  import {
    careField,
    confidenceStatus,
    displayUnit,
    editTarget,
    formatValue,
    isUncited,
    sentenceName,
    sortCareValues,
    sourceKind,
  } from './care';
  import { formatDate } from './labels';

  let {
    values,
    specimenId,
    speciesId,
    onsaved,
  }: {
    values: CareValue[];
    specimenId: string;
    speciesId: string | null;
    /** Called after a successful save so the page can re-read the API. */
    onsaved?: () => void;
  } = $props();

  const rows = $derived(sortCareValues(values));
  const uncited = $derived(rows.filter(isUncited));

  /** Corrections this page has saved. The contract has no way to read a
   *  specimen override back — `Specimen` carries no `*_override` field — so
   *  without this the reader would save an edit and watch the old value return.
   *  Flagged to the maintainers in the PR; until then the screen says what it did
   *  rather than pretending the edit vanished. */
  let saved = $state<Record<string, string>>({});

  let editing = $state<CareValue | null>(null);
  let open = $state(false);
  let numberDraft = $state<number | null>(null);
  let textDraft = $state('');
  let booleanDraft = $state(false);
  let saving = $state(false);
  let failure = $state<string | null>(null);

  const spec = $derived(editing ? careField(editing.field) : null);
  const target = $derived(editing ? editTarget(editing.field, specimenId, speciesId) : null);

  function startEdit(value: CareValue) {
    editing = value;
    failure = null;
    const kind = careField(value.field).kind;
    numberDraft = kind === 'number' && typeof value.value === 'number' ? value.value : null;
    textDraft = kind === 'text' && value.value != null ? String(value.value) : '';
    booleanDraft = kind === 'boolean' && value.value === true;
    open = true;
  }

  function draft(): number | string | boolean | null {
    if (!spec) return null;
    if (spec.kind === 'number') return numberDraft;
    if (spec.kind === 'boolean') return booleanDraft;
    return textDraft.trim() === '' ? null : textDraft.trim();
  }

  async function save() {
    if (!editing || !target) return;
    saving = true;
    failure = null;
    const field = editing.field;
    const value = draft();
    try {
      await saveCareValue(target, value, fetch);
      saved = { ...saved, [field]: formatValue(value, field, editing.unit) };
      open = false;
      editing = null;
      onsaved?.();
    } catch (cause) {
      failure = reason(cause);
    } finally {
      saving = false;
    }
  }
</script>

{#if uncited.length}
  <!-- Never a colour alone, and never below the fold: the whole 's
       consequence is that this warning reaches the person holding the can. -->
  <p class="uncited" role="note">
    <strong>No source for {uncited.length === 1 ? 'one value' : `${uncited.length} values`}.</strong
    >
    {uncited.map((v) => careField(v.field).plain).join(', ')} —
    {uncited.length === 1 ? 'this figure is' : 'these figures are'} a guess nobody has attested. There
    is no soil sensor to catch it if it is wrong, so check
    {uncited.length === 1 ? 'it' : 'them'} against a plant you trust and correct
    {uncited.length === 1 ? 'it' : 'them'} here.
  </p>
{/if}

<ul class="values">
  {#each rows as value (value.field)}
    {@const spec_ = careField(value.field)}
    <li class="value" class:uncited-row={isUncited(value)}>
      <div class="head">
        <span class="name">
          <span class="plain">{spec_.plain}</span>
          {#if spec_.themed}<span class="themed">{spec_.themed}</span>{/if}
        </span>
        <span class="reading">{formatValue(value.value, value.field, value.unit)}</span>
      </div>
      <StatusPill status={confidenceStatus(value.confidence, value.is_user_override)} />
      <p class="source">
        {#if value.source}
          Source: {sourceKind(value.source.kind)} —
          {#if value.source.url}
            <a href={value.source.url} rel="noreferrer noopener" target="_blank"
              >{value.source.title}</a
            >
          {:else}
            {value.source.title}
          {/if}
          {#if value.source.license}<span class="licence">({value.source.license})</span>{/if}
          <span class="retrieved"
            >Read {formatDate(value.source.retrieved_at, 'at an unrecorded time')}.</span
          >
        {:else}
          Source: none. Nothing was consulted for this figure.
        {/if}
      </p>
      {#if value.note}<p class="note">{value.note}</p>{/if}
      {#if saved[value.field]}
        <p class="saved" role="status">
          Your correction — {saved[value.field]} — was saved to the Register. It is not shown above yet:
          the API does not return specimen overrides, which is a contract gap raised with the maintainers.
        </p>
      {/if}
      <div class="act">
        <Button
          variant="quiet"
          plain="Correct {sentenceName(value.field)}"
          themed="Amend the record"
          icon="quill"
          onclick={() => startEdit(value)}
        />
      </div>
    </li>
  {/each}
</ul>

<Dialog
  bind:open
  themed="Amend the record"
  plain={editing ? `Correct ${sentenceName(editing.field)}` : 'Correct a care value'}
  description={target?.scope}
  onclose={() => {
    editing = null;
    failure = null;
  }}
>
  {#if editing && spec}
    {#if spec.kind === 'number'}
      <NumberField
        bind:value={numberDraft}
        plain={spec.plain}
        themed={spec.themed}
        hint={spec.hint}
        suffix={displayUnit(editing.unit) ?? spec.unit}
        min={spec.min}
        max={spec.max}
        step={spec.step ?? 'any'}
      />
    {:else if spec.kind === 'boolean'}
      <Toggle bind:checked={booleanDraft} plain={spec.plain} hint={spec.hint} />
    {:else}
      <TextField bind:value={textDraft} plain={spec.plain} themed={spec.themed} hint={spec.hint} />
    {/if}

    <p class="dialog-note">
      Your correction wins over every source. The sourced value stays on the record underneath it.
    </p>

    {#if !target}
      <p class="dialog-error" role="alert">
        This value belongs to a species, and this plant has not been matched to one yet. Identify it
        on the Register entry first.
      </p>
    {/if}
    {#if failure}
      <p class="dialog-error" role="alert">Not saved. {failure}</p>
    {/if}
  {/if}

  {#snippet footer()}
    <Button
      plain="Save correction"
      themed="Set it down"
      icon="check"
      loading={saving}
      disabled={!target}
      busyPlain="Saving…"
      onclick={save}
    />
    <Button variant="quiet" plain="Cancel" onclick={() => (open = false)} />
  {/snippet}
</Dialog>

<style>
  .uncited {
    margin: 0 0 var(--moh-space-4);
    padding: var(--moh-space-3);
    border: 2px solid var(--moh-ailing);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
    font-size: var(--moh-text-sm);
  }
  .values {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-4);
  }
  .value {
    display: grid;
    gap: var(--moh-space-2);
    padding-block-end: var(--moh-space-4);
    border-block-end: 1px solid var(--moh-border);
  }
  .value:last-child {
    border-block-end: 0;
    padding-block-end: 0;
  }
  .uncited-row {
    border-inline-start: 3px solid var(--moh-ailing);
    padding-inline-start: var(--moh-space-3);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--moh-space-2);
  }
  .name {
    display: flex;
    flex-direction: column;
  }
  .plain {
    font-size: var(--moh-text-base);
  }
  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .reading {
    font-family: var(--moh-font-mono);
    font-size: var(--moh-text-lg);
  }
  .source,
  .note,
  .saved {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .saved {
    color: var(--moh-ink);
  }
  .licence,
  .retrieved {
    white-space: nowrap;
  }
  .act {
    display: flex;
  }
  .dialog-note {
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .dialog-error {
    font-size: var(--moh-text-sm);
    color: var(--moh-ailing);
  }
</style>
