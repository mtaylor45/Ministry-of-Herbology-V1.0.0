<script lang="ts">
  import { onMount } from 'svelte';
  import { afterNavigate } from '$app/navigation';
  import Icon from '$ui/Icon.svelte';
  import Label from '$ui/Label.svelte';
  import { formatAsOf } from '$ui/stale';
  import {
    connectivity,
    dispatch,
    sentence,
    shouldNotice,
    startConnectivity,
  } from './connectivity';

  /** The strip above the section bar that says the greenhouse could not be
   *  reached and what is being shown instead. It never claims to be fresh,
   *  and it names the age of the copy when the copy carried one. The design system.
   *
   *  It is rendered by `Nav`, which is the shell's one component that every
   *  page already mounts, so the shell says it on every screen without a
   *  change to the layout file. */

  const state = $derived($connectivity);
  const show = $derived(shouldNotice(state));
  const says = $derived(sentence(state, (iso) => formatAsOf(iso)));
  const themed = $derived(
    state.online ? 'The owl came back empty-handed' : 'The owls are grounded',
  );
  const plain = $derived(state.online ? 'Showing a saved copy' : 'You are offline');

  onMount(startConnectivity);
  afterNavigate(() => dispatch({ type: 'navigated' }));
</script>

{#if show}
  <div class="offline" role="status" data-online={state.online}>
    <span class="glyph" aria-hidden="true"><Icon name="stale" size={20} /></span>
    <div class="text">
      <p class="head"><Label {themed} {plain} where="OfflineNotice" /></p>
      <p class="says">{says}</p>
    </div>
  </div>
{/if}

<style>
  .offline {
    position: fixed;
    inset-inline: 0;
    /* just above the section bar, which sits on the home indicator */
    bottom: calc(var(--moh-tap) + env(safe-area-inset-bottom));
    z-index: 9;
    display: flex;
    align-items: flex-start;
    gap: var(--moh-space-3);
    padding: var(--moh-space-2) var(--moh-space-4);
    background: var(--moh-surface-sunken);
    color: var(--moh-ink);
    border-top: 1px solid var(--moh-border);
    border-inline-start: 4px solid var(--moh-parched);
    box-shadow: var(--moh-shadow);
  }
  .glyph {
    color: var(--moh-parched);
    margin-top: 2px;
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  .head,
  .says {
    margin: 0;
  }
  .says {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  @media (min-width: 900px) {
    .offline {
      inset-inline: 14rem 0;
      bottom: 0;
      border-top-left-radius: var(--moh-radius-lg);
    }
  }
</style>
