<script lang="ts">
  import type { Snippet } from 'svelte';
  import Label from './Label.svelte';
  import { hasThemed } from './pairing';

  /** A panel on a raised surface. The header is optional; when it is there it
   *  is a real heading, so a screen reader can navigate the page by them. */
  let {
    themed,
    plain,
    level = 2,
    tone = 'plain',
    action,
    children,
    footer,
  }: {
    themed?: string;
    plain?: string;
    /** Heading level, so cards nest properly inside a page's outline. */
    level?: 2 | 3 | 4;
    tone?: 'plain' | 'accent' | 'danger';
    action?: Snippet;
    children: Snippet;
    footer?: Snippet;
  } = $props();

  const hasHeader = $derived(Boolean(plain?.trim()) || hasThemed(themed));
</script>

<section class="card" data-tone={tone}>
  {#if hasHeader}
    <header class="head">
      {#if level === 2}
        <h2><Label {themed} {plain} display="below" where="Card" /></h2>
      {:else if level === 3}
        <h3><Label {themed} {plain} display="below" where="Card" /></h3>
      {:else}
        <h4><Label {themed} {plain} display="below" where="Card" /></h4>
      {/if}
      {#if action}<div class="action">{@render action()}</div>{/if}
    </header>
  {/if}
  <div class="body">{@render children()}</div>
  {#if footer}<footer class="foot">{@render footer()}</footer>{/if}
</section>

<style>
  .card {
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius-lg);
    padding: var(--moh-space-4);
    box-shadow: var(--moh-shadow);
  }
  /* Tone is a hint, never the message: the copy inside says what is going on. */
  .card[data-tone='accent'] {
    border-inline-start: 4px solid var(--moh-accent);
  }
  .card[data-tone='danger'] {
    border-inline-start: 4px solid var(--moh-danger);
  }
  .head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--moh-space-3);
    margin-bottom: var(--moh-space-3);
  }
  h2,
  h3,
  h4 {
    margin: 0;
    font-family: var(--moh-font-display);
  }
  h2 {
    font-size: var(--moh-text-xl);
  }
  h3 {
    font-size: var(--moh-text-lg);
  }
  h4 {
    font-size: var(--moh-text-base);
  }
  .body > :global(:first-child) {
    margin-top: 0;
  }
  .body > :global(:last-child) {
    margin-bottom: 0;
  }
  .foot {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
    margin-top: var(--moh-space-4);
  }
</style>
