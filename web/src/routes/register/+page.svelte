<script lang="ts">
  /** The Register — the household's inventory.
   *
   *  The filters are a form whose result is an address: submitting it
   *  navigates to `/register?…`, so a filter can be bookmarked and the back
   *  button undoes one. Without script the same form is a plain GET form and
   *  lands on the same address.
   *
   *  Archived plants are kept out of the list by the API unless asked for with
   *  `status=archived` (the inventory API's `listSpecimens`). a plant set aside is
   *  still named — so the Status filter offers them by name and the page says
   *  where they are, rather than letting them vanish.
   */
  import { tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { Button, EmptyState, Icon, SelectField, StaleNotice, StatusPill, TextField } from '$ui';
  import type { PageData } from './$types';
  import PageTitle from '../shared/PageTitle.svelte';
  import { specimenStatus } from '../specimen/[id]/labels';
  import AddPlant from './AddPlant.svelte';
  import { reads, reason } from './api';
  import {
    NO_FILTERS,
    STATUSES,
    STATUS_WORDS,
    emptySentence,
    groupLine,
    hasFilters,
    locationOption,
    nextTaskLine,
    placeLine,
    registerHref,
    sortLocations,
    speciesIndex,
    speciesLine,
    summarySentence,
    toxicityMark,
    type RegisterFilters,
    type RegisterSpecimen,
  } from './register';

  let { data }: { data: PageData } = $props();

  const locations = $derived(sortLocations(data.locations.value ?? []));
  const toxicity = $derived(data.species.value ? speciesIndex(data.species.value) : null);

  // ------------------------------------------------------------ the form

  let draft = $state<RegisterFilters>({ ...NO_FILTERS });
  // The address is the truth. When it changes — a submit, the back button, a
  // bookmark — the form is put back to say what the list is showing.
  $effect.pre(() => {
    draft = { ...data.filters };
  });

  const locationOptions = $derived([
    { value: '', plain: 'Every location' },
    ...locations.map((l) => ({ value: l.id, plain: locationOption(l) })),
  ]);
  const outdoorOptions = [
    { value: '', plain: 'Indoors and outdoors' },
    { value: 'false', plain: 'Indoors only' },
    { value: 'true', plain: 'Outdoors only' },
  ];
  const statusOptions = [
    { value: '', plain: 'Every plant still in the Register' },
    ...STATUSES.map((s) => ({
      value: s,
      plain: s === 'archived' ? 'Archived — set aside, still on record' : STATUS_WORDS[s],
    })),
  ];
  // The API answers `toxic_to_pets=false` with every plant not *known* to be
  // toxic — a species nobody has checked included. The option says so: it is
  // not "safe for pets", and it must not read as that.
  const toxicOptions = [
    { value: '', plain: 'Any' },
    { value: 'true', plain: 'Toxic to pets' },
    { value: 'false', plain: 'Not marked toxic to pets (includes unchecked)' },
  ];

  async function apply(event: SubmitEvent) {
    event.preventDefault();
    await goto(registerHref(draft), { keepFocus: true, noScroll: true });
  }

  // ------------------------------------------------------------ the list

  let extra = $state<RegisterSpecimen[]>([]);
  let cursor = $state<string | null>(null);
  let loadingMore = $state(false);
  let moreError = $state<string | null>(null);
  let listEl = $state<HTMLUListElement | null>(null);

  $effect.pre(() => {
    extra = [];
    cursor = data.page.value?.next_cursor ?? null;
    moreError = null;
  });

  const items = $derived([...(data.page.value?.items ?? []), ...extra]);
  const total = $derived(data.page.value?.total);
  const empty = $derived(emptySentence(data.filters, locations));

  async function showMore() {
    if (!cursor) return;
    loadingMore = true;
    moreError = null;
    const firstNew = items.length;
    try {
      const next = await reads.specimens(data.filters, cursor, fetch);
      extra = [...extra, ...next.items];
      cursor = next.next_cursor ?? null;
      await tick();
      // Keyboard and screen-reader users land on the first new row rather
      // than back at the button, which has moved down the page.
      listEl?.querySelectorAll<HTMLAnchorElement>('a.row')[firstNew]?.focus();
    } catch (cause) {
      moreError = reason(cause);
    } finally {
      loadingMore = false;
    }
  }
</script>

<svelte:head><title>The Register — The Ministry of Herbology</title></svelte:head>

<PageTitle themed="The Register" plain="Inventory — every plant in the household">
  <p class="jump"><a href="#add-plant">Add a plant</a></p>
</PageTitle>

<form
  class="filters"
  method="get"
  action="/register"
  role="search"
  aria-label="Search and filter the Register"
  onsubmit={apply}
>
  <TextField
    name="q"
    themed="Seek by name"
    plain="Search"
    hint="A nickname, a common name or a Latin one"
    autocomplete="off"
    bind:value={draft.q}
  />
  <div class="grid">
    <SelectField
      name="location_id"
      plain="Location"
      themed="Where it stands"
      options={locationOptions}
      bind:value={draft.location_id}
      hint={data.locations.error
        ? `Locations could not be read: ${data.locations.error}`
        : undefined}
    />
    <SelectField
      name="outdoor"
      plain="Indoors or out"
      options={outdoorOptions}
      bind:value={draft.outdoor}
    />
    <SelectField
      name="status"
      plain="Status"
      themed="State of health"
      options={statusOptions}
      bind:value={draft.status}
    />
    <SelectField
      name="toxic_to_pets"
      plain="Toxic to pets"
      options={toxicOptions}
      bind:value={draft.toxic_to_pets}
    />
  </div>
  <div class="actions">
    <Button type="submit" themed="Consult the Register" plain="Apply filters" icon="search" />
    {#if hasFilters(data.filters)}
      <a class="clear" href="/register">Clear every filter</a>
    {/if}
  </div>
</form>

<section class="results" aria-labelledby="results-heading">
  <h2 id="results-heading" class="visually-hidden">Plants</h2>

  {#if data.page.error}
    <StaleNotice plain="The Register" asOf={null} reason={data.page.error} />
    <p class="note">
      The list could not be read, so nothing below is a statement about which plants you have.
    </p>
  {:else}
    <p class="summary" role="status">
      {summarySentence(items.length, total, data.filters, locations)}
    </p>

    {#if data.species.error}
      <p class="note">
        Toxicity could not be read ({data.species.error}), so no row below says whether a plant is
        toxic. That is not the same as safe.
      </p>
    {/if}

    {#if items.length}
      <ul class="rows" bind:this={listEl}>
        {#each items as specimen (specimen.id)}
          {@const mark = toxicityMark(specimen, toxicity)}
          {@const group = groupLine(specimen)}
          {@const next = nextTaskLine(specimen.next_task)}
          <li>
            <a class="row" href="/specimen/{specimen.id}/register">
              <span class="thumb" aria-hidden="true">
                {#if specimen.primary_photo_url}
                  <img src={specimen.primary_photo_url} alt="" loading="lazy" decoding="async" />
                {:else}
                  <Icon name="leaf" size={24} />
                {/if}
              </span>
              <span class="body">
                <span class="name">{specimen.display_name}</span>
                <span class="line">{speciesLine(specimen)}</span>
                <span class="line">{placeLine(specimen)}{group ? ` · ${group}` : ''}</span>
                <span class="marks">
                  <StatusPill status={specimenStatus(specimen.status)} />
                  <span class="tox" data-warn={mark.warn}>
                    {#if mark.warn}<Icon name="warning" size={16} />{/if}
                    {mark.text}
                  </span>
                </span>
                {#if next}<span class="line">{next}</span>{/if}
              </span>
            </a>
          </li>
        {/each}
      </ul>

      {#if cursor}
        <div class="more">
          <Button
            variant="quiet"
            themed="Turn the page"
            plain="Show more"
            loading={loadingMore}
            busyPlain="Fetching more plants…"
            onclick={showMore}
          />
          {#if moreError}<p class="note" role="alert">{moreError}</p>{/if}
        </div>
      {/if}
    {:else}
      <EmptyState
        icon={hasFilters(data.filters) ? 'search' : 'seedling'}
        themed={hasFilters(data.filters) ? 'No entry answers' : 'The Register is blank'}
        plain={empty.plain}
        body={empty.body}
        level={2}
      />
    {/if}

    {#if data.filters.status !== 'archived'}
      <p class="aside">
        Plants set aside are kept, not deleted:
        <a href={registerHref({ ...data.filters, status: 'archived' })}>show archived plants</a>.
      </p>
    {/if}
  {/if}
</section>

<AddPlant
  {locations}
  species={data.species.value ?? []}
  speciesError={data.species.error}
  locationsError={data.locations.error}
/>

<style>
  .jump {
    margin: var(--moh-space-2) 0 0;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  a {
    color: var(--moh-ink);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  a:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }

  .filters {
    display: grid;
    gap: var(--moh-space-3);
    padding: var(--moh-space-4);
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius-lg);
    margin-bottom: var(--moh-space-6);
  }
  .grid {
    display: grid;
    gap: var(--moh-space-3);
  }
  @media (min-width: 40rem) {
    .grid {
      grid-template-columns: 1fr 1fr;
    }
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--moh-space-4);
  }
  .clear {
    display: inline-flex;
    align-items: center;
    min-height: var(--moh-tap);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }

  .summary,
  .note,
  .aside {
    margin: 0 0 var(--moh-space-3);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .aside {
    margin-top: var(--moh-space-4);
  }
  .aside a {
    display: inline-block;
    min-height: var(--moh-tap);
    line-height: var(--moh-tap);
  }

  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  .row {
    display: flex;
    gap: var(--moh-space-3);
    align-items: flex-start;
    min-height: var(--moh-row);
    padding: var(--moh-space-3);
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    color: var(--moh-ink);
    text-decoration: none;
  }
  .row:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .thumb {
    flex: none;
    width: 4rem;
    height: 4rem;
    display: grid;
    place-items: center;
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-gold-line);
    border-radius: var(--moh-radius);
    color: var(--moh-ink-muted);
    overflow: hidden;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .body {
    display: grid;
    gap: var(--moh-space-1);
    min-width: 0;
  }
  .name {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .line {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
    overflow-wrap: anywhere;
  }
  .marks {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
    align-items: center;
  }
  .tox {
    display: inline-flex;
    align-items: center;
    gap: var(--moh-space-1);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  /* A warning is the icon *and* the words *and* full-strength ink — never the
     colour alone. Ink, not the danger red: this is a fact about a plant, not
     an error in the app. */
  .tox[data-warn='true'] {
    color: var(--moh-ink);
    font-weight: 600;
  }
  .more {
    margin-top: var(--moh-space-4);
    display: grid;
    justify-items: start;
    gap: var(--moh-space-2);
  }
</style>
