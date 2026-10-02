<script lang="ts">
  /** A page's one `<h1>`: the themed name and the plain one under it.
   *
   *  The Register, the Office and the Grounds each opened without a level-one
   *  heading (the design system's an earlier release audit, `page-has-heading-one`). One component, so the next
   *  screen does not have to rediscover the pairing and the outline. */
  import type { Snippet } from 'svelte';

  let { themed, plain, children }: { themed: string; plain: string; children?: Snippet } = $props();
</script>

<header class="title">
  <h1>
    <span class="themed">{themed}</span>
    <span class="plain">{plain}</span>
  </h1>
  {#if children}{@render children()}{/if}
</header>

<style>
  .title {
    margin-bottom: var(--moh-space-4);
  }
  h1 {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin: 0;
  }
  .themed {
    font-family: var(--moh-font-display);
  }
  .plain {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    font-weight: normal;
  }
</style>
