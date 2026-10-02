<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import type { IconName } from './icons';

  /** Nothing here yet — and what to do about it. An empty state without an
   *  action is a dead end, so `action` is where the next step goes. */
  let {
    icon = 'seedling',
    themed,
    plain,
    body,
    level,
    action,
  }: {
    icon?: IconName;
    themed?: string;
    plain: string;
    /** A plain sentence saying why it is empty. */
    body?: string;
    /** Given, the title is a heading of this level rather than a paragraph —
     *  for an empty state that *is* the page, like the error page, which
     *  otherwise has no heading at all (axe `page-has-heading-one`). */
    level?: 1 | 2 | 3;
    action?: Snippet;
  } = $props();
</script>

<div class="empty">
  <span class="glyph" aria-hidden="true"><Icon name={icon} size={40} strokeWidth={1.2} /></span>
  {#if level === 1}
    <h1 class="title"><Label {themed} {plain} display="below" where="EmptyState" /></h1>
  {:else if level === 2}
    <h2 class="title"><Label {themed} {plain} display="below" where="EmptyState" /></h2>
  {:else if level === 3}
    <h3 class="title"><Label {themed} {plain} display="below" where="EmptyState" /></h3>
  {:else}
    <p class="title"><Label {themed} {plain} display="below" where="EmptyState" /></p>
  {/if}
  {#if body}<p class="body">{body}</p>{/if}
  {#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--moh-space-3);
    padding: var(--moh-space-8) var(--moh-space-4);
    text-align: center;
    border: 1px dashed var(--moh-border);
    border-radius: var(--moh-radius-lg);
    background: var(--moh-surface-sunken);
  }
  .glyph {
    color: var(--moh-ink-muted);
  }
  .title {
    margin: 0;
    font-size: var(--moh-text-lg);
    font-family: var(--moh-font-body);
    font-weight: 400;
    line-height: 1.55;
  }
  .body {
    margin: 0;
    max-width: 34ch;
    color: var(--moh-ink-muted);
  }
</style>
