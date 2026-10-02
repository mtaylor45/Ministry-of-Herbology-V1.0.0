<script lang="ts">
  /** A description list of plain facts.
   *
   *  Not a control — no button, pill, card or field is reimplemented here. It
   *  is the `<dl>` that the Register and Compendium facets both lay their
   *  fields out in, so the two read the same way.
   */
  import type { Fact } from './facts';

  let { facts }: { facts: Fact[] } = $props();
</script>

<dl class="facts">
  {#each facts as fact (fact.plain)}
    <div class="fact">
      <dt>
        <span class="term">{fact.plain}</span>
        {#if fact.themed}<span class="themed">{fact.themed}</span>{/if}
      </dt>
      <dd>
        {fact.value}
        {#if fact.note}<span class="note">{fact.note}</span>{/if}
      </dd>
    </div>
  {/each}
</dl>

<style>
  .facts {
    margin: 0;
    display: grid;
    gap: var(--moh-space-3);
  }
  .fact {
    display: grid;
    gap: var(--moh-space-1);
  }
  @media (min-width: 40rem) {
    .fact {
      grid-template-columns: 14rem 1fr;
      align-items: baseline;
      gap: var(--moh-space-4);
    }
  }
  dt {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--moh-space-2);
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .themed {
    font-family: var(--moh-font-display);
  }
  dd {
    margin: 0;
  }
  .note {
    display: block;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
</style>
