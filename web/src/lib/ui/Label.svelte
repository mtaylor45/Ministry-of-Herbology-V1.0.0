<script lang="ts">
  import { hasThemed, requirePair, type PlainDisplay } from './pairing';

  /** A themed string and its plain meaning. The themed half never travels alone.
   *  Every component in this library renders its labels through here. */
  let {
    themed,
    plain,
    display = 'beside',
    where = 'Label',
  }: {
    themed?: string;
    plain?: string;
    /** `beside` on one line, `below` stacked, `screen-reader` plain read aloud only. */
    display?: PlainDisplay;
    /** Component name, so a pairing failure names the offender. */
    where?: string;
  } = $props();

  const safePlain = $derived(requirePair(themed, plain, where));
</script>

{#if hasThemed(themed)}
  <span class="label" data-display={display}>
    <span class="themed">{themed}</span>
    {#if display === 'screen-reader'}
      <span class="visually-hidden"> — {safePlain}</span>
    {:else}
      <span class="plain">{safePlain}</span>
    {/if}
  </span>
{:else}
  <span class="label" data-display="plain-only">{safePlain}</span>
{/if}

<style>
  .label {
    display: inline-flex;
    gap: var(--moh-space-2);
    align-items: baseline;
    min-width: 0;
  }
  .label[data-display='below'] {
    flex-direction: column;
    gap: 0;
    align-items: flex-start;
  }
  /* Cormorant Garamond sets small for its point size; without this the display
     half reads as the subordinate one, which is backwards. */
  .themed {
    font-family: var(--moh-font-display);
    font-size: 1.08em;
    font-weight: 500;
  }
  /* The plain half is de-emphasised by typography, not only by tone: the
     utility sans against the display serif (guide §3) is what tells the two
     halves apart, and it keeps working where tone cannot.

     `--moh-plain-ink` is muted against a page surface and is re-declared by any
     control that paints its own background. It used to be `--moh-ink-muted`
     outright, which on a filled primary button measured 1.26:1 on parchment and
     1.01:1 on greenhouse — a WCAG AA failure at any size, and the original-theme rule broken
     twice over, since the readable half was the unreadable one. `contrast.test.ts`
     measures every surface this can land on and fails on a new filled control
     that forgets to say which ink its plain half takes. */
  .plain {
    color: var(--moh-plain-ink, var(--moh-ink-muted));
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .label[data-display='beside'] .plain::before {
    content: '— ';
  }
</style>
