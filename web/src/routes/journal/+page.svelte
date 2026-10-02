<script lang="ts">
  /** The Naturalist's Journal — the book view.
   *
   *  It pages through **every plant in the register**, one leaf each, because
   *  the releases's exit criterion is a coverage target and a book built from the
   *  plates it happens to have would read as complete while three plants were
   *  missing from it (`plates.ts` has the argument).
   *
   *  Accessibility, since this is an image-heavy surface:
   *
   *  - every plate has real alt text that says what it is *and* whether it was
   *    generated — `altTextFor` in `plates.ts`;
   *  - page turning works from the keyboard: the two buttons are real buttons
   *    in the tab order, and ← / → turn the page when focus is not in a text
   *    field. The handler checks the target so typing a field note cannot turn
   *    the page out from under the writer;
   *  - the leaf is a live region announcing "leaf 4 of 12" on each turn, so a
   *    screen-reader user is told the page changed rather than discovering it;
   *  - the page-turn transition is a fade of a few hundred milliseconds and is
   *    removed entirely under `prefers-reduced-motion` — the media query is in
   *    the stylesheet below, so it holds even if the script never runs.
   *
   *  Colour comes from the design system's tokens only. There is not a literal in the
   *  stylesheet.
   */
  import { Button, Card, EmptyState } from '$ui';
  import PlatePage from './PlatePage.svelte';
  import { invalidateAll } from '$app/navigation';
  import { writes, reason } from './api';
  import {
    buildPages,
    clampIndex,
    coverage,
    coverageBySpecimen,
    coverageSentence,
    indexOfSpecimen,
  } from './plates';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const plates = $derived(data.plates.value ?? []);
  const specimens = $derived(data.specimens.value ?? []);
  const members = $derived(data.members.value ?? []);
  const pages = $derived(buildPages(specimens, plates));
  const count = $derived(coverage(pages));
  const reasons = $derived(coverageBySpecimen(data.coverage.value));

  let index = $state(0);
  let approving = $state<string | null>(null);
  let approvalError = $state<string | null>(null);
  let touched = $state(false);

  /** Open at the plant the link asked for, until the reader turns a page. */
  $effect(() => {
    if (touched || !data.openAt || !pages.length) return;
    const at = indexOfSpecimen(pages, data.openAt);
    if (at !== null) index = at;
  });

  const current = $derived(pages[clampIndex(index, pages)] ?? null);
  const canTurnBack = $derived(index > 0);
  const canTurnOn = $derived(index < pages.length - 1);

  function turn(by: number) {
    touched = true;
    index = clampIndex(index + by, pages);
  }

  /** ← and → turn the page, unless the reader is typing. */
  function onkeydown(event: KeyboardEvent) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return;
    if (event.key === 'ArrowLeft' && canTurnBack) {
      event.preventDefault();
      turn(-1);
    } else if (event.key === 'ArrowRight' && canTurnOn) {
      event.preventDefault();
      turn(1);
    }
  }

  async function approve(plateId: string) {
    const member = members[0];
    if (!member) {
      approvalError =
        'No household member is recorded, and a plate is accepted by somebody — so there is nobody to record as having accepted it.';
      return;
    }
    approving = plateId;
    approvalError = null;
    try {
      await writes.approve(plateId, member.id, fetch);
      await invalidateAll();
    } catch (cause) {
      approvalError = reason(cause);
    } finally {
      approving = null;
    }
  }
</script>

<svelte:window on:keydown={onkeydown} />

<svelte:head>
  <title>The Naturalist's Journal — The Ministry of Herbology</title>
</svelte:head>

<div class="journal">
  <header class="masthead">
    <h1>
      <span class="themed">The Naturalist's Journal</span>
      <span class="plain">Illustrated plates, one leaf per plant</span>
    </h1>
    <p class="coverage">{coverageSentence(count)}</p>
  </header>

  {#if data.specimens.error}
    <Card
      themed="The register is out of reach"
      plain="Cannot say how many plants there are"
      level={2}
    >
      <p class="problem">
        {data.specimens.error} Without the register this page cannot tell a plant with no plate from a
        plant that is not here, so it is not showing a book at all rather than showing a short one.
      </p>
    </Card>
  {:else if data.plates.error}
    <Card themed="The plates are out of reach" plain="Could not load the illustrations" level={2}>
      <p class="problem">{data.plates.error}</p>
    </Card>
  {:else if !pages.length}
    <EmptyState
      icon="seedling"
      themed="An unopened volume"
      plain="There is nothing in the register yet"
      body="Add a plant and its leaf appears here, with a plate when one can be found for it."
    />
  {:else if current}
    <div class="book">
      <p class="folio" aria-live="polite">
        Leaf {index + 1} of {pages.length}
      </p>

      {#key current.specimen.id}
        <div class="leaf-frame">
          <PlatePage
            page={current}
            coverage={reasons.get(current.specimen.id)}
            approving={approving === current.plate?.id}
            canApprove={Boolean(members.length)}
            onapprove={approve}
          />
        </div>
      {/key}

      {#if approvalError}
        <p class="problem" role="alert">{approvalError}</p>
      {/if}

      <nav class="turn" aria-label="Turn the page">
        <Button
          variant="quiet"
          plain="Previous leaf"
          disabled={!canTurnBack}
          onclick={() => turn(-1)}
        />
        <Button
          variant="quiet"
          plain="Next leaf"
          icon="chevronRight"
          disabled={!canTurnOn}
          onclick={() => turn(1)}
        />
      </nav>

      <p class="hint">The left and right arrow keys turn the page.</p>
    </div>
  {/if}
</div>

<style>
  .journal {
    display: grid;
    gap: var(--moh-space-6);
    padding: var(--moh-space-4);
    max-width: 44rem;
    margin: 0 auto;
  }

  .masthead {
    display: grid;
    gap: var(--moh-space-2);
    border-bottom: 1px solid var(--moh-gold-line);
    padding-bottom: var(--moh-space-3);
  }

  h1 {
    margin: 0;
    display: grid;
    gap: var(--moh-space-1);
  }

  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-2xl);
    color: var(--moh-ink);
    line-height: 1.1;
  }

  .plain {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    letter-spacing: var(--moh-tracking-meta);
    text-transform: uppercase;
    color: var(--moh-ink-muted);
  }

  .coverage {
    margin: 0;
    color: var(--moh-ink);
  }

  .book {
    display: grid;
    gap: var(--moh-space-4);
  }

  .folio {
    margin: 0;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    letter-spacing: var(--moh-tracking-meta);
    text-transform: uppercase;
    color: var(--moh-ink-muted);
  }

  /* The page turn. A short fade, and nothing else — a page-flip animation on a
     surface somebody reads twelve times in a row is a surface that gets tiring.
     `{#key}` above remounts the leaf, which is what starts this. */
  .leaf-frame {
    animation: leaf-in var(--moh-motion-sheet) var(--moh-motion-ease);
  }

  @keyframes leaf-in {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  /* The definition of done. Honoured in the stylesheet rather than in script, so it holds
     whether or not the component ever hydrates. */
  @media (prefers-reduced-motion: reduce) {
    .leaf-frame {
      animation: none;
    }
  }

  .turn {
    display: flex;
    gap: var(--moh-space-3);
    flex-wrap: wrap;
  }

  .hint {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .problem {
    margin: 0;
    color: var(--moh-ink);
  }
</style>
