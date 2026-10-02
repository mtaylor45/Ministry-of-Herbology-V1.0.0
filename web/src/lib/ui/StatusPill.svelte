<script lang="ts">
  import type { Status } from './status';

  /** Renders the themed label with its plain meaning beside it — never alone. */
  let { status, showPlain = true }: { status: Status; showPlain?: boolean } = $props();
</script>

<span class="pill" data-tone={status.tone}>
  <span class="themed">{status.themed}</span>
  {#if showPlain}
    <span class="plain"> — {status.plain}</span>
  {:else}
    <span class="visually-hidden"> — {status.plain}</span>
  {/if}
</span>

<style>
  .pill {
    display: inline-flex;
    align-items: baseline;
    gap: 0.15em;
    padding: var(--moh-space-1) var(--moh-space-3);
    border-radius: var(--moh-radius);
    border: 1px solid currentColor;
    font-size: var(--moh-text-sm);
    line-height: 1.4;
  }
  .pill[data-tone='parched'] {
    color: var(--moh-parched);
  }
  .pill[data-tone='sated'] {
    color: var(--moh-sated);
  }
  .pill[data-tone='frost'] {
    color: var(--moh-frost);
  }
  .pill[data-tone='thriving'] {
    color: var(--moh-thriving);
  }
  .pill[data-tone='ailing'] {
    color: var(--moh-ailing);
  }

  .themed {
    font-family: var(--moh-font-display);
  }
  /* Same contract as Label: muted on a page surface, the control's own ink
     inside anything that paints a background under it. */
  .plain {
    color: var(--moh-plain-ink, var(--moh-ink-muted));
    font-family: var(--moh-font-ui);
  }
</style>
