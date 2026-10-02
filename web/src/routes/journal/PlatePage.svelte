<script lang="ts">
  /** One page of the book: a plant, its plate, and where the plate came from.
   *
   *  Three states, and the one that took the most thought is the third:
   *
   *  - an approved plate, shown with its provenance note;
   *  - a plate nobody has accepted yet, shown *and marked as not accepted*,
   *    with the approval left outstanding — see `plates.ts` for why it is shown
   *    rather than hidden;
   *  - no plate, which gets a page of its own naming the plant. A book that
   *    silently skipped it would read as complete at nine pages out of twelve.
   *
   *  The image is `loading="lazy"` and carries explicit intrinsic dimensions
   *  via `aspect-ratio` on its frame, so turning pages does not reflow the
   *  caption underneath it while the next plate arrives.
   */
  import { Button, EmptyState, Icon, Label } from '$ui';
  import ProvenanceNote from './ProvenanceNote.svelte';
  import { absenceSentence, altTextFor, type JournalPage, type PlateCoverageEntry } from './plates';

  let {
    page,
    coverage,
    approving = false,
    canApprove = false,
    onapprove,
  }: {
    page: JournalPage;
    /** This plant's coverage entry, when `/journal/coverage` answered. */
    coverage?: PlateCoverageEntry;
    approving?: boolean;
    canApprove?: boolean;
    onapprove?: (plateId: string) => void;
  } = $props();

  const alt = $derived(altTextFor(page));
  const name = $derived(page.botanicalName ?? page.specimen.display_name);
</script>

<article class="leaf" aria-labelledby="leaf-heading-{page.specimen.id}">
  <header class="plate-head">
    <h3 id="leaf-heading-{page.specimen.id}" class="name">{page.specimen.display_name}</h3>
    {#if page.botanicalName && page.botanicalName !== page.specimen.display_name}
      <p class="botanical">{page.botanicalName}</p>
    {/if}
  </header>

  {#if page.plate}
    <figure class="figure">
      <div class="frame">
        <img src={page.plate.image_url} {alt} loading="lazy" decoding="async" />
      </div>
      <figcaption class="caption">
        {#if page.state === 'waiting'}
          <p class="waiting">
            <span class="glyph" aria-hidden="true"><Icon name="warning" size={16} /></span>
            <Label
              themed="Not yet entered in the register"
              plain="No one has accepted this plate for this plant yet"
              display="below"
              where="PlatePage"
            />
          </p>
        {/if}
        <ProvenanceNote plate={page.plate} />
        {#if page.state === 'waiting' && canApprove}
          <div class="approve">
            <Button
              variant="primary"
              themed="Into the register"
              plain="Accept this plate"
              full
              loading={approving}
              busyPlain="Accepting this plate…"
              onclick={() => onapprove?.(page.plate!.id)}
            />
          </div>
        {/if}
      </figcaption>
    </figure>
  {:else}
    <EmptyState
      icon="book"
      themed="A blank leaf"
      plain="No plate for {name}"
      body={absenceSentence(page, coverage)}
    />
    {#if coverage?.reason}
      <!-- The pipeline's own sentence, under the reader's. Written for an
           operator reading a log, so it is smaller and second — but it is
           shown, because it is the thing that says what actually happened. -->
      <p class="pipeline-reason">{coverage.reason}</p>
    {/if}
  {/if}
</article>

<style>
  .leaf {
    display: grid;
    gap: var(--moh-space-4);
  }

  .plate-head {
    display: grid;
    gap: var(--moh-space-1);
  }

  .name {
    margin: 0;
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-xl);
    color: var(--moh-ink);
  }

  .botanical {
    margin: 0;
    font-style: italic;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }

  .figure {
    margin: 0;
    display: grid;
    gap: var(--moh-space-3);
  }

  /* A fixed aspect ratio so the caption does not jump while the next plate
     loads. Plates are portrait; this is the ratio the mock encoder draws. */
  .frame {
    aspect-ratio: 3 / 4;
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-gold-line);
    border-radius: var(--moh-radius);
    overflow: hidden;
    display: grid;
    place-items: center;
  }

  .frame img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }

  .caption {
    display: grid;
    gap: var(--moh-space-3);
  }

  .waiting {
    display: flex;
    gap: var(--moh-space-2);
    align-items: flex-start;
    margin: 0;
    color: var(--moh-ink);
  }

  .waiting .glyph {
    display: inline-flex;
    flex: none;
    margin-top: 2px;
    color: var(--moh-parched);
  }

  .approve {
    display: flex;
  }

  .pipeline-reason {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
    text-align: center;
  }
</style>
