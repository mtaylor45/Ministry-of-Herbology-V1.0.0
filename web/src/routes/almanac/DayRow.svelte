<script lang="ts">
  /** One day of the ten-day strip.
   *
   *  The bar is a picture of the two numbers printed beside it, and nothing
   *  else: high, low, rain and frost are all present as words, so the row reads
   *  the same in bright sun, in greyscale and aloud. The bar itself is hidden
   *  from assistive technology for exactly that reason — it would otherwise
   *  announce the same figures a second time.
   */
  import Icon from '$ui/Icon.svelte';
  import { FROST_NOTE, formatTemp, rainSentence, rangeBar } from './forecast';
  import type { DailyRow } from './forecast';

  let {
    row,
    domain,
    freezingAt,
  }: {
    row: DailyRow;
    domain: { min: number; max: number };
    /** Where freezing falls on the shared scale, as a percentage, or null when
     *  the ten days never come near it. */
    freezingAt?: number | null;
  } = $props();

  const bar = $derived(rangeBar(row, domain));
</script>

<div class="day" data-frost={row.frost ?? undefined}>
  <p class="when">
    <time datetime={row.day}>{row.label}</time>
    {#if row.condition}
      <span class="condition">
        {#if row.condition.icon}
          <span class="glyph" aria-hidden="true"><Icon name={row.condition.icon} size={16} /></span>
        {/if}
        {row.condition.plain}
      </span>
    {/if}
  </p>

  <div class="range">
    <span class="low">{formatTemp(row.low)}</span>
    <span class="track" aria-hidden="true">
      {#if freezingAt !== null && freezingAt !== undefined}
        <span class="freezing" style:inset-inline-start={`${freezingAt}%`}></span>
      {/if}
      {#if bar}
        <span
          class="fill"
          style:inset-inline-start={`${bar.startPct}%`}
          style:inline-size={`${bar.lengthPct}%`}
        ></span>
      {/if}
    </span>
    <span class="high">{formatTemp(row.high)}</span>
  </div>

  <p class="rain">
    <span class="glyph" aria-hidden="true"><Icon name="rain" size={16} /></span>
    {rainSentence(row)}
  </p>

  {#if row.frost}
    <p class="frost">
      <span class="glyph" aria-hidden="true"><Icon name="frost" size={18} /></span>
      <span class="themed">{FROST_NOTE[row.frost].themed}</span>
      <span class="plain">— {FROST_NOTE[row.frost].plain}</span>
    </p>
  {/if}
</div>

<style>
  .day {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--moh-space-2);
    padding: var(--moh-space-3) 0;
    border-bottom: 1px solid var(--moh-border);
  }
  .when {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--moh-space-2);
    margin: 0;
  }
  time {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
  }
  .condition,
  .rain {
    display: flex;
    align-items: center;
    gap: var(--moh-space-1);
    margin: 0;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .range {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
  }
  .low,
  .high {
    flex: none;
    min-width: 5.5ch;
    font-variant-numeric: tabular-nums;
    font-size: var(--moh-text-sm);
  }
  .high {
    text-align: end;
  }
  .track {
    position: relative;
    flex: 1;
    height: var(--moh-space-2);
    border-radius: 999px;
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-border);
  }
  .fill {
    position: absolute;
    inset-block: -1px;
    border-radius: 999px;
    background: var(--moh-accent);
  }
  .freezing {
    position: absolute;
    inset-block: -4px;
    inline-size: 2px;
    background: var(--moh-frost);
  }
  .frost {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--moh-space-1);
    margin: 0;
    color: var(--moh-frost);
  }
  .day[data-frost='frost'] .fill {
    background: var(--moh-frost);
  }
  .glyph {
    display: inline-flex;
  }
  .themed {
    font-family: var(--moh-font-display);
  }
  .plain {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
</style>
