<script lang="ts">
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import { staleSentence, type Timestamp } from './stale';

  /** What you are looking at is old, and here is how old.
   *
   *  The rule from the brief: say what is stale rather than lying. This never
   *  claims to be fresh, never hides the age, and names the data it covers so
   *  the reader knows which part of the screen to distrust. */
  let {
    themed,
    plain,
    asOf,
    reason,
    now = new Date(),
    retryPlain = 'Try again',
    onretry,
  }: {
    themed?: string;
    /** The plain name of the data: "The Almanac forecast". */
    plain: string;
    /** When it was last fetched. `null` means it never was. */
    asOf: Timestamp;
    /** Why it could not be refreshed, in plain language. */
    reason?: string;
    /** Injected so the sentence is testable. */
    now?: Date;
    retryPlain?: string;
    onretry?: () => void;
  } = $props();

  const sentence = $derived(staleSentence(plain, asOf, now));
</script>

<div class="stale" role="status">
  <span class="glyph" aria-hidden="true"><Icon name="stale" size={20} /></span>
  <div class="text">
    <p class="head"><Label {themed} plain="Out of date" where="StaleNotice" /></p>
    <p class="says">{sentence}</p>
    {#if reason}<p class="reason">{reason}</p>{/if}
  </div>
  {#if onretry}
    <div class="action">
      <Button variant="quiet" plain={retryPlain} onclick={onretry} />
    </div>
  {/if}
</div>

<style>
  .stale {
    display: flex;
    align-items: flex-start;
    gap: var(--moh-space-3);
    padding: var(--moh-space-3);
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-border);
    border-inline-start: 4px solid var(--moh-parched);
    border-radius: var(--moh-radius);
  }
  .glyph {
    color: var(--moh-parched);
    margin-top: 2px;
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  .head {
    margin: 0;
  }
  .says,
  .reason {
    margin: var(--moh-space-1) 0 0;
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .action {
    flex: none;
  }
</style>
