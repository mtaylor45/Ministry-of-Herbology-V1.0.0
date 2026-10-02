<script lang="ts">
  /** Add a plant: type a name, see what the botanical sources call it, pick
   *  one, and the plant is in the Register.
   *
   *  Two steps rather than one because a typed name is not a species. The botany worker's
   *  `POST /taxon/resolve` answers with ranked candidates, each with its own
   *  confidence and source; the person chooses, and the choice is
   *  what the inventory API's `POST /specimens` is sent. If no source recognises the name — or
   *  none can be reached — the plant can still be added under the typed name:
   *  The inventory API keeps it as the nickname and the enrichment queue keeps trying.
   *
   *  A candidate is matched to a species the household already has by its
   *  accepted name, so the new plant shares that species' cited care at once
   *  (`species_id`); otherwise only the name is sent and C resolves it.
   */
  import { goto } from '$app/navigation';
  import { Button, Card, NumberField, SelectField, TextField } from '$ui';
  import { reason, writes, type SpeciesRow, type TaxonCandidate } from './api';
  import { candidateLabel, createBody, knownSpeciesId } from './addPlant';
  import { locationOption, type RegisterLocation } from './register';

  let {
    locations,
    species,
    speciesError = null,
    locationsError = null,
  }: {
    locations: RegisterLocation[];
    species: SpeciesRow[];
    speciesError?: string | null;
    locationsError?: string | null;
  } = $props();

  let name = $state('');
  let nickname = $state('');
  let locationId = $state('');
  let count = $state<number | null>(1);

  type Lookup =
    | { state: 'idle' }
    | { state: 'looking' }
    | { state: 'found'; typed: string; candidates: TaxonCandidate[] }
    | { state: 'failed'; typed: string; reason: string };
  let lookup = $state<Lookup>({ state: 'idle' });
  /** Index into the candidates, or `'typed'` for "add it under the typed name". */
  let choice = $state<string>('');
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let nameError = $state<string | undefined>(undefined);

  const locationOptions = $derived([
    { value: '', plain: 'Not placed yet' },
    ...locations.map((l) => ({ value: l.id, plain: locationOption(l) })),
  ]);

  async function look(event: SubmitEvent) {
    event.preventDefault();
    const typed = name.trim();
    if (!typed) {
      nameError = 'Type the plant’s name first — common or Latin.';
      return;
    }
    nameError = undefined;
    lookup = { state: 'looking' };
    try {
      const candidates = await writes.resolve(typed, fetch);
      lookup = { state: 'found', typed, candidates };
      choice = candidates.length ? '0' : 'typed';
    } catch (cause) {
      lookup = { state: 'failed', typed, reason: reason(cause) };
      choice = 'typed';
    }
  }

  async function add() {
    if (lookup.state !== 'found' && lookup.state !== 'failed') return;
    const candidate =
      lookup.state === 'found' && choice !== 'typed' ? lookup.candidates[Number(choice)] : null;
    saving = true;
    saveError = null;
    try {
      const created = await writes.create(
        createBody({
          typed: lookup.typed,
          candidate,
          speciesId: candidate ? knownSpeciesId(candidate, species) : null,
          nickname,
          locationId,
          count,
        }),
        fetch,
      );
      await goto(`/specimen/${created.id}/register`);
    } catch (cause) {
      saveError = reason(cause);
    } finally {
      saving = false;
    }
  }
</script>

<section id="add-plant" class="add" tabindex="-1" aria-label="Add a plant">
  <Card themed="Enter a new specimen" plain="Add a plant" level={2}>
    <form class="step" onsubmit={look}>
      <TextField
        name="name"
        themed="What is it called?"
        plain="Plant name"
        hint="Common or Latin, e.g. “sweet basil” or “Ocimum basilicum”. A cultivar in quotes is kept."
        required
        error={nameError}
        bind:value={name}
      />
      <Button
        type="submit"
        variant="quiet"
        themed="Consult the herbals"
        plain="Look it up"
        icon="search"
        loading={lookup.state === 'looking'}
        busyPlain="Asking the botanical sources…"
      />
    </form>

    <div aria-live="polite">
      {#if lookup.state === 'found' || lookup.state === 'failed'}
        <fieldset class="choices">
          <legend>
            {#if lookup.state === 'found' && lookup.candidates.length}
              Which plant is “{lookup.typed}”?
            {:else if lookup.state === 'found'}
              No botanical source recognised “{lookup.typed}”.
            {:else}
              The botanical sources could not be asked: {lookup.reason}
            {/if}
          </legend>
          {#if lookup.state === 'found'}
            {#each lookup.candidates as candidate, i (i)}
              <label class="choice">
                <input type="radio" name="candidate" value={String(i)} bind:group={choice} />
                <span>{candidateLabel(candidate)}</span>
              </label>
            {/each}
          {/if}
          <label class="choice">
            <input type="radio" name="candidate" value="typed" bind:group={choice} />
            <span>
              None of these — add it as “{lookup.typed}” and let the Ministry keep looking. Its care
              stays unknown until a source is found.
            </span>
          </label>
        </fieldset>

        <div class="extras">
          <TextField
            name="nickname"
            themed="What the household calls it"
            plain="Nickname (optional)"
            bind:value={nickname}
          />
          <SelectField
            name="location_id"
            plain="Location"
            themed="Where it will stand"
            options={locationOptions}
            hint={locationsError ? `Locations could not be read: ${locationsError}` : undefined}
            bind:value={locationId}
          />
          <NumberField
            name="count"
            plain="How many plants this entry stands for"
            hint="More than one makes it a group — a row of lavender, a tray of seedlings."
            min={1}
            step={1}
            bind:value={count}
          />
        </div>
        {#if speciesError}
          <p class="note">
            The household’s species list could not be read ({speciesError}), so the new plant is
            sent by name and matched to its species by the server.
          </p>
        {/if}
        <Button
          themed="Inscribe it"
          plain="Add to the Register"
          icon="plus"
          loading={saving}
          busyPlain="Adding the plant…"
          disabled={!choice}
          onclick={add}
        />
        {#if saveError}<p class="note" role="alert">{saveError}</p>{/if}
      {/if}
    </div>
  </Card>
</section>

<style>
  .add {
    margin-top: var(--moh-space-8);
  }
  .add:focus {
    outline: none;
  }
  .step {
    display: grid;
    gap: var(--moh-space-3);
    justify-items: start;
  }
  .step :global(> *:first-child) {
    justify-self: stretch;
  }
  .choices {
    margin: var(--moh-space-4) 0 0;
    padding: 0;
    border: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  legend {
    padding: 0;
    margin-bottom: var(--moh-space-2);
    font-weight: 600;
  }
  .choice {
    display: flex;
    gap: var(--moh-space-3);
    align-items: flex-start;
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface);
    cursor: pointer;
  }
  .choice input {
    margin-top: 0.25em;
    width: 1.25rem;
    height: 1.25rem;
    accent-color: var(--moh-accent);
    flex: none;
  }
  .choice:has(input:focus-visible) {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .extras {
    display: grid;
    gap: var(--moh-space-3);
    margin: var(--moh-space-4) 0;
  }
  .note {
    margin: var(--moh-space-3) 0;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
</style>
