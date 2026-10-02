<script lang="ts">
  /** The head of the Specimen page: which plant this is, how it is faring, and
   *  whether anything is still on its way from the enrichment queue.
   *
   *  The facets themselves are the page body. Navigation between them is the
   *  "see also" block each facet carries, which is the cross-linking the plan
   *  asks for rather than a tab strip bolted on top of it.
   */
  import { invalidate } from '$app/navigation';
  import { StatusPill } from '$ui';
  import type { Snippet } from 'svelte';
  import type { LayoutData } from './$types';
  import { enrichmentProgress, specimenStatus } from './labels';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  const specimen = $derived(data.specimen);
  const species = $derived(data.species.value);
  const progress = $derived(enrichmentProgress(species?.enrichment_state, Boolean(data.speciesId)));

  /** Re-reads while the queue is still working. Stops after roughly a minute
   *  and a half: the exit criterion is 60 seconds, so a job still running well
   *  past it is stuck, and a page that keeps polling forever is a page that
   *  never admits it. */
  const POLL_MS = 4000;
  const POLL_LIMIT = 22;
  let polls = $state(0);

  $effect(() => {
    if (!progress.busy || polls >= POLL_LIMIT) return;
    const timer = setInterval(() => {
      polls += 1;
      void invalidate('moh:specimen');
    }, POLL_MS);
    return () => clearInterval(timer);
  });

  const gaveUp = $derived(progress.busy && polls >= POLL_LIMIT);
</script>

<svelte:head>
  <title>{specimen.display_name} — The Ministry of Herbology</title>
</svelte:head>

<header class="plant">
  <p class="eyebrow">Specimen</p>
  <h1>{specimen.display_name}</h1>
  {#if specimen.species}
    <p class="botanical">
      <em>{specimen.species.accepted_name}</em>{#if specimen.cultivar}
        &nbsp;&lsquo;{specimen.cultivar}&rsquo;{/if}{#if specimen.species.common_name}
        — {specimen.species.common_name}{/if}
    </p>
  {:else}
    <p class="botanical">Not yet matched to a species.</p>
  {/if}
  <div class="pills">
    <StatusPill status={specimenStatus(specimen.status)} />
  </div>
  <p class="where">
    {#if specimen.location}
      {specimen.location.name} — {specimen.is_outdoor ? 'outdoors' : 'indoors'},
      {specimen.in_container ? 'in a container' : 'in the ground'}
    {:else}
      No location recorded — {specimen.is_outdoor ? 'outdoors' : 'indoors'}
    {/if}
  </p>
</header>

{#if progress.busy || progress.state === 'failed' || progress.state === 'unidentified'}
  <section
    class="owl"
    data-state={progress.state}
    aria-live="polite"
    aria-busy={progress.busy ? 'true' : 'false'}
  >
    <p class="owl-themed">{progress.themed}</p>
    <p class="owl-plain">{progress.plain}</p>
    {#if progress.busy}
      <p class="owl-plain">
        {#if gaveUp}
          Still not finished after a minute and a half. Nothing more will arrive on its own — reload
          the page to look again.
        {:else}
          Checking again every few seconds. Nothing below is final until this says so.
        {/if}
      </p>
    {/if}
  </section>
{/if}

{#if data.species.error}
  <p class="load-error" role="alert">
    The species record could not be read. {data.species.error}
  </p>
{/if}

{@render children()}

<style>
  .plant {
    margin-block-end: var(--moh-space-6);
  }
  .eyebrow {
    margin: 0;
    font-size: var(--moh-text-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--moh-ink-muted);
  }
  h1 {
    margin: 0;
  }
  .botanical,
  .where {
    margin: var(--moh-space-1) 0 0;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .pills {
    margin-block-start: var(--moh-space-3);
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
  }
  .owl {
    margin-block-end: var(--moh-space-6);
    padding: var(--moh-space-4);
    border: 1px solid var(--moh-border);
    border-inline-start: 3px solid var(--moh-accent);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
  }
  .owl[data-state='failed'] {
    border-inline-start-color: var(--moh-ailing);
  }
  .owl-themed {
    margin: 0;
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
  }
  .owl-plain {
    margin: var(--moh-space-1) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .load-error {
    margin-block-end: var(--moh-space-4);
    color: var(--moh-ailing);
    font-size: var(--moh-text-sm);
  }
</style>
