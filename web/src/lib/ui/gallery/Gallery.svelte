<script lang="ts">
  import GalleryPane from './GalleryPane.svelte';
  import { THEMES } from '../theme';

  /** Every component in the library, side by side in both themes.
   *
   *  The panes carry their own `data-theme`, so this page shows parchment and
   *  night greenhouse at once without running the app, hitting the API or
   *  switching a preference. If a change looks right in one theme and wrong in
   *  the other, it shows up here before it reaches a screen. */
</script>

<svelte:head><title>Component gallery — The Ministry of Herbology</title></svelte:head>

<header class="intro">
  <h1>Component gallery <span class="plain">The design system, both themes</span></h1>
  <p>
    Every control the design system ships, rendered twice: once on parchment, once in the night
    greenhouse. No API, no fixtures, no login. Themed wording always travels with its plain meaning,
    touch targets are at least 44px, and nothing here says anything with colour alone.
  </p>
</header>

<div class="panes">
  {#each THEMES as theme (theme)}
    <section class="pane" data-theme={theme} aria-label="{theme} theme">
      <GalleryPane {theme} />
    </section>
  {/each}
</div>

<style>
  .intro {
    margin-bottom: var(--moh-space-6);
  }
  .intro p {
    color: var(--moh-ink-muted);
    max-width: 62ch;
  }
  .plain {
    display: block;
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .panes {
    display: grid;
    gap: var(--moh-space-4);
    grid-template-columns: 1fr;
  }
  .pane {
    background: var(--moh-surface);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius-lg);
    padding: var(--moh-space-4);
  }
  @media (min-width: 900px) {
    .panes {
      grid-template-columns: 1fr 1fr;
      align-items: start;
    }
  }
</style>
