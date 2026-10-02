<script lang="ts">
  /** This plant's place on the map, and the way there.
   *
   *  The map-to-plant direction of the earlier cross-link is the maps module's and is already
   *  built: every pin is a real anchor to this page. This is the direction
   *  back, and its whole job is to be honest about which of several true
   *  answers applies — the states are named and resolved in `mapPlace.ts`.
   *
   *  The caveat renders beside the sentence it qualifies and above the link it
   *  qualifies, never in a tooltip or behind a disclosure. On the
   *  uncalibrated sheet, the caveat *is* the useful half.
   */
  import { Card, ListRow, StaleNotice } from '$ui';
  import type { Place } from './mapPlace';

  let { place }: { place: Place } = $props();
</script>

<Card themed="On the plans" plain="Where it is on the map" level={2}>
  {#if place.state === 'unknown'}
    <!-- The sentence says what is not known; the notice says why, in the same
         words the rest of the app uses for a read it could not make. Neither
         is "this plant has no pin", which is what a bare empty panel would
         have implied. -->
    <p class="sentence" data-placed="false">{place.sentence}</p>
    <StaleNotice
      themed="The plans cannot be consulted"
      plain="This plant’s place on the map"
      asOf={null}
      reason={place.caveat ?? undefined}
    />
  {:else}
    <p class="sentence" data-placed={place.placed}>{place.sentence}</p>
    {#if place.caveat}
      <p class="caveat">{place.caveat}</p>
    {/if}
  {/if}

  <ul class="links">
    <li>
      <ListRow
        themed={place.linkThemed}
        plain={place.linkPlain}
        meta={place.layer ? `Opens ${place.layer.name}` : 'Opens the map'}
        href={place.href}
        icon="pin"
      />
    </li>
  </ul>
</Card>

<style>
  .sentence {
    margin: 0;
    color: var(--moh-ink);
  }
  /* Placed and unplaced are different facts, so they do not look identical —
     and the difference is the words first, with weight behind them. Never
     colour alone. */
  .sentence[data-placed='true'] {
    font-weight: 600;
  }
  .caveat {
    margin: var(--moh-space-3) 0 0;
    padding-inline-start: var(--moh-space-3);
    border-inline-start: 3px solid var(--moh-accent);
    color: var(--moh-ink);
    font-size: var(--moh-text-sm);
  }
  .links {
    list-style: none;
    margin: var(--moh-space-4) 0 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
</style>
