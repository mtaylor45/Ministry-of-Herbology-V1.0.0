<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import type { IconName } from './icons';

  /** One row of a list, sized for a thumb rather than a cursor.
   *
   *  The whole row is the target — there is exactly one interactive element in
   *  it — so nobody has to hit a 12px chevron in the rain. */
  let {
    themed,
    plain,
    meta,
    href,
    onclick,
    icon,
    selected = false,
    disabled = false,
    leading,
    trailing,
  }: {
    themed?: string;
    plain: string;
    /** Secondary plain text: a location, a due date, a count. */
    meta?: string;
    href?: string;
    onclick?: (event: MouseEvent) => void;
    icon?: IconName;
    selected?: boolean;
    disabled?: boolean;
    leading?: Snippet;
    trailing?: Snippet;
  } = $props();

  const interactive = $derived(Boolean(href) || Boolean(onclick));
</script>

{#snippet inner()}
  {#if leading}
    <span class="lead">{@render leading()}</span>
  {:else if icon}
    <span class="lead"><Icon name={icon} size={22} /></span>
  {/if}
  <span class="text">
    <Label {themed} {plain} display="below" where="ListRow" />
    {#if meta}<span class="meta">{meta}</span>{/if}
  </span>
  {#if trailing}
    <span class="trail">{@render trailing()}</span>
  {:else if href}
    <span class="trail"><Icon name="chevronRight" size={18} /></span>
  {/if}
{/snippet}

{#if href}
  <a class="row" class:selected {href} aria-current={selected ? 'true' : undefined}>
    {@render inner()}
  </a>
{:else if onclick}
  <button class="row" type="button" class:selected {disabled} aria-pressed={selected} {onclick}>
    {@render inner()}
  </button>
{:else}
  <div class="row" class:selected data-interactive={interactive}>
    {@render inner()}
  </div>
{/if}

<style>
  .row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: var(--moh-space-3);
    min-height: var(--moh-row);
    padding: var(--moh-space-3) var(--moh-space-4);
    background: var(--moh-surface-raised);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    color: var(--moh-ink);
    font: inherit;
    text-align: start;
    text-decoration: none;
  }
  a.row,
  button.row {
    cursor: pointer;
  }
  .row.selected {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
  }
  .lead,
  .trail {
    display: inline-flex;
    align-items: center;
    color: var(--moh-ink-muted);
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  /* Metadata gets §3's utility sans. Not its uppercase or its wide tracking:
     those are for a word or two on a tab, and this line is a sentence with a
     date in it. §25 outranks §3 where the two disagree. */
  .meta {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  /* A row that cannot be opened still has to be read — it says why in its
     meta line. Muted ink on the sunken surface rather than a dimmed row: the
     dim one measured below 3:1 on the night greenhouse. */
  button.row:disabled {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
    cursor: not-allowed;
  }
</style>
