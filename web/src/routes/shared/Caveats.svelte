<script lang="ts">
  /** How much to trust the number or the instruction beside this, and every
   *  reason it might be wrong — in the engine's own words, in full, on screen.
   *
   *  Not a tooltip, not an icon, not a colour. Under the design the weather
   *  engines are the only authority on whether an outdoor plant is watered or
   *  carried indoors, and the way they fail is by losing an input and going on
   *  answering in the same confident voice. A caveat the reader has to hover to
   *  find is a caveat that is not there on a phone in the rain.
   *
   *  `detail` is rendered verbatim: The weather engine writes those sentences to be
   *  shown as they stand (`workers/weather/quality.py`), and paraphrasing them
   *  here is how six wordings of one caveat come to exist. */
  import StatusPill from '$ui/StatusPill.svelte';
  import Icon from '$ui/Icon.svelte';
  import type { Status } from '$ui/status';
  import type { Assessment } from './assessment';
  import {
    capSentence,
    caveats,
    measurementConfidence,
    reportsItsOwnConfidence,
  } from './assessment';

  /** The Almanac's silence, kept as the default because it is where the notice
   *  was first needed: its two endpoints are outside the design altogether. */
  const ALMANAC_SILENCE =
    'does not say how sure it is. A stale ingest or a locally computed evaporation figure lowers ' +
    'what the engine behind it is worth, and the design requires that to be declared on the water ' +
    'balance and the frost guard — but not on these two endpoints, which carry nothing of the ' +
    'sort. Read nothing here as a clean bill of health. Asked of the maintainers this release.';

  let {
    payload,
    what,
    /** Say so when the endpoint reports no confidence at all. See the seam in
     *  `assessment.ts`: silence has to look like silence, not like a clean bill
     *  of health. */
    noticeWhenSilent = true,
    /** The sentence shown when nothing is reported. It names the endpoints that
     *  are silent and why, so it belongs to the screen rather than here; this
     *  default is the Almanac's, which is where the notice was first needed. */
    silentNotice = ALMANAC_SILENCE,
    /** The pill for this confidence level. The default vocabulary is about
     *  *readings* — "read through cloud" — which is right for a forecast and
     *  wrong for a watering worked out from an uncited interval, so a screen
     *  with a different kind of answer passes its own words. */
    status,
    /** `heading` puts "Why it may be wrong" in the page outline, which is right
     *  when the block is one panel on a screen. In a list of eight tasks it is
     *  eight identical headings naming no plant, so a row passes `text`. */
    labelAs = 'heading',
  }: {
    payload: Assessment | null | undefined;
    /** Plain name of the thing being assessed: "This forecast". */
    what: string;
    noticeWhenSilent?: boolean;
    silentNotice?: string;
    status?: Status;
    labelAs?: 'heading' | 'text';
  } = $props();

  const reports = $derived(reportsItsOwnConfidence(payload));
  const reasons = $derived(caveats(payload));
</script>

{#if reports}
  <div class="assessment" class:degraded={reasons.length > 0}>
    <p class="level">
      <span class="what">{what}</span>
      <StatusPill status={status ?? measurementConfidence(payload?.confidence)} />
    </p>

    {#if reasons.length}
      {#if labelAs === 'heading'}
        <h3 class="why">Why it may be wrong</h3>
      {:else}
        <p class="why">Why it may be wrong</p>
      {/if}
      <ul>
        {#each reasons as reason (reason.code)}
          <li>
            <span class="glyph" aria-hidden="true"><Icon name="warning" size={18} /></span>
            <span class="says">
              <span class="detail">{reason.detail}</span>
              <span class="cap">{capSentence(reason)}</span>
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{:else if noticeWhenSilent}
  <p class="silent">
    <span class="glyph" aria-hidden="true"><Icon name="warning" size={18} /></span>
    <span>{what} {silentNotice}</span>
  </p>
{/if}

<style>
  .assessment {
    padding: var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
  }
  /* The border is a hint; the words inside are the message. */
  .assessment.degraded {
    border-inline-start: 4px solid var(--moh-parched);
  }
  .level {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--moh-space-2);
    margin: 0;
  }
  .what {
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .why {
    margin: var(--moh-space-3) 0 var(--moh-space-2);
    font-weight: 700;
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-sm);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--moh-ink-muted);
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: var(--moh-space-3);
  }
  li {
    display: flex;
    gap: var(--moh-space-2);
    align-items: flex-start;
  }
  .glyph {
    flex: none;
    color: var(--moh-parched);
    margin-top: 2px;
  }
  .says {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
  }
  .detail {
    font-size: var(--moh-text-base);
  }
  .cap {
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .silent {
    display: flex;
    gap: var(--moh-space-2);
    align-items: flex-start;
    margin: 0;
    padding: var(--moh-space-3);
    border: 1px dashed var(--moh-border);
    border-radius: var(--moh-radius);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
</style>
