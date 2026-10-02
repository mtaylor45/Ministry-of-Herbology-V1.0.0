<script lang="ts">
  /** The Grounds.
   *
   *  The maps module built the whole surface behind one component, so this route is nearly
   *  one element — as it should be. What is left for the route is the part a
   *  component cannot know: the reads, what to say when one of them fails, and
   *  which sheet to open when a Specimen page sent somebody here to look at one
   *  particular plant.
   */
  import { Grounds } from '$map';
  import { StaleNotice } from '$ui';
  import { arrival, orderLayers } from './arrival';
  import { placeable, unpinnedCount } from './roster';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const layers = $derived(data.layers.value ?? []);
  const pins = $derived(data.pins.value ?? []);
  const zones = $derived(data.zones.value ?? []);
  const register = $derived(data.register.value?.entries ?? null);

  // The pins the map draws, plus a placeable row for every plant in the
  // Register that no sheet holds a pin for. Without this the screen offers no
  // way to place a first pin at all on a live deployment — see `roster.ts`.
  const rows = $derived(placeable(layers, pins, register));
  const waiting = $derived(unpinnedCount(pins, register));

  const came = $derived(arrival(data.fromSpecimenId, layers, rows, register !== null));
  const ordered = $derived(orderLayers(layers, came?.layerId ?? data.wantedLayerId));
</script>

<svelte:head>
  <title>The Grounds — The Ministry of Herbology</title>
</svelte:head>

<!-- The page's one level-one heading (the design system's an earlier release audit, page-has-heading-one). The
     visible title is the maps module's, an <h2> inside `Grounds.svelte`, which this route may
     not edit; until H takes a `level` prop the h1 is announced, not
     drawn twice. -->
<h1 class="visually-hidden">The Grounds — Maps of the house and the land</h1>

{#if data.layers.error}
  <StaleNotice
    themed="The plans cannot be fetched"
    plain="The map"
    asOf={null}
    reason={data.layers.error}
  />
{:else if data.pins.error}
  <!-- A sheet with no pins drawn on it looks like a sheet with nothing on it,
       which is a different and untrue statement. So the map waits. -->
  <StaleNotice
    themed="The pins cannot be fetched"
    plain="The pin list"
    asOf={null}
    reason={data.pins.error}
  />
  <p class="aside">
    The plans themselves are fine. The map is held back rather than drawn empty, because an empty
    sheet and a sheet whose pins could not be read look the same and mean different things.
  </p>
{:else}
  {#if came}
    <!-- Not a live region: this is page content, present on load and in
         reading order above the map, rather than an update to announce. -->
    <section class="arrival">
      <p class="who">{came.sentence}</p>
      <p class="back">
        <a href={came.backHref}>Back to {came.name}’s Register entry</a>
      </p>
    </section>
  {/if}

  {#if data.register.error}
    <StaleNotice
      themed="The Register cannot be read"
      plain="The list of plants"
      asOf={null}
      reason={data.register.error}
    />
    <p class="aside">
      The sheets and the pins below are current. What is missing is the plants that have no pin yet
      — they cannot be listed, so they cannot be placed from this screen until the Register answers
      again.
    </p>
  {:else if data.register.value?.truncated}
    <p class="aside">
      The Register is longer than this screen reads in one go, so some plants with no pin may not be
      listed below. Those already pinned are all here.
    </p>
  {:else if waiting > 0}
    <p class="aside">
      {waiting === 1 ? '1 plant in the Register has' : `${waiting} plants in the Register have`} no pin
      yet. {waiting === 1 ? 'It is' : 'They are'} in the list below the map, under whichever sheet is
      open, waiting to be placed.
    </p>
  {/if}

  {#if data.zones.error}
    <StaleNotice
      themed="The zones are not drawn"
      plain="The zone overlay"
      asOf={null}
      reason={data.zones.error}
    />
  {/if}

  <!-- Keyed on the sheet that should be open. `Grounds` seeds its own state
       from these props once and then owns it, which is right for a surface
       that writes through the API — but it means a second arrival asking for a
       different sheet would otherwise land on the first one. Remounting is
       the honest answer, and the key changes only when the sheet does. -->
  {#key ordered[0]?.id ?? ''}
    <Grounds layers={ordered} pins={rows} {zones} />
  {/key}
{/if}

<style>
  .arrival {
    margin-block-end: var(--moh-space-4);
    padding: var(--moh-space-4);
    border: 1px solid var(--moh-border);
    border-inline-start: 3px solid var(--moh-accent);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
  }
  .who {
    margin: 0;
    color: var(--moh-ink);
    font-size: var(--moh-text-base);
  }
  .back {
    margin: var(--moh-space-2) 0 0;
    font-size: var(--moh-text-sm);
  }
  .back a {
    color: var(--moh-ink);
  }
  .aside {
    margin: var(--moh-space-3) 0 0;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
</style>
