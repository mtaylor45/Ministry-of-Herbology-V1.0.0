<script lang="ts">
  import { Button, Icon } from '$ui';
  import type { PinRow } from './pins';
  import type { MapLayer } from './types';

  /** The non-visual equivalent of the map, and not a consolation prize.
   *
   * The definition of done says WCAG AA is part of done, and a map is the hardest surface in
   * this app to get there: a marker is a positioned `div`, a pointer target
   * with no name, no role and no place in the reading order. This list is the
   * same rows the markers are drawn from — so "tap the pin" and "press Enter
   * on the row" reach the same Specimen page, and every pin is in the tab
   * order whether or not anybody can see the sheet.
   *
   * It is shown, not hidden. A sighted keyboard user needs it as much as a
   * screen-reader user does, and a visually-hidden list is one refactor away
   * from being a visually-hidden *stale* list nobody notices.
   */
  let {
    layer,
    rows,
    selectedId = null,
    placingId = null,
    onplace,
    onlift,
    onhighlight,
  }: {
    layer: MapLayer;
    rows: PinRow[];
    /** The row the map is currently highlighting, if any. */
    selectedId?: string | null;
    /** The row whose pin is being moved by keyboard, if any. */
    placingId?: string | null;
    onplace?: (row: PinRow) => void;
    onlift?: (row: PinRow) => void;
    onhighlight?: (row: PinRow | null) => void;
  } = $props();

  const placed = $derived(rows.filter((row) => row.placed));
  const unplacedRows = $derived(rows.filter((row) => !row.placed));
</script>

<section class="pins" aria-labelledby="pin-list-heading">
  <h3 id="pin-list-heading">
    <span class="themed">The Roll of Plantings</span>
    <span class="plain">Every pin on {layer.name}, as a list</span>
  </h3>

  {#if rows.length === 0}
    <p class="none">
      Nothing is pinned to {layer.name} yet. Choose a plant below to place the first one.
    </p>
  {:else}
    <ol class="rows">
      {#each placed as row (row.specimenId)}
        <li
          class="row"
          class:selected={row.specimenId === selectedId}
          class:placing={row.specimenId === placingId}
        >
          <a
            class="link"
            href={row.href}
            aria-describedby={`pos-${row.specimenId}`}
            onfocus={() => onhighlight?.(row)}
            onmouseenter={() => onhighlight?.(row)}
            onblur={() => onhighlight?.(null)}
            onmouseleave={() => onhighlight?.(null)}
          >
            <Icon name="pin" size={18} />
            <span class="name">{row.name}</span>
            <span class="visually-hidden">
              — pin {row.ordinal} of {row.total}. Opens its Specimen page.
            </span>
          </a>
          <p class="position" id={`pos-${row.specimenId}`}>{row.position}</p>
          <div class="actions">
            <Button
              variant="quiet"
              plain={row.specimenId === placingId ? 'Moving — press Escape to stop' : 'Move pin'}
              onclick={() => onplace?.(row)}
            />
            <Button variant="quiet" plain="Lift pin off the map" onclick={() => onlift?.(row)} />
          </div>
        </li>
      {/each}
    </ol>

    {#if unplacedRows.length}
      <h4 class="sub">
        <span class="themed">Awaiting a place</span>
        <span class="plain">
          — in the Register, not yet on {layer.name}
        </span>
      </h4>
      <ul class="rows">
        {#each unplacedRows as row (row.specimenId)}
          <li class="row">
            <a class="link" href={row.href}>
              <Icon name="seedling" size={18} />
              <span class="name">{row.name}</span>
            </a>
            <p class="position">{row.position}</p>
            <div class="actions">
              <Button variant="quiet" plain="Place on the map" onclick={() => onplace?.(row)} />
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .pins {
    margin-top: var(--moh-space-6);
  }

  h3,
  .sub {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin: 0 0 var(--moh-space-3);
  }
  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
    color: var(--moh-ink);
  }
  .plain {
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .sub {
    margin-top: var(--moh-space-6);
  }

  .none {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
    margin: 0;
  }

  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
  }

  .row {
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-raised);
    padding: var(--moh-space-3);
  }
  /* Selection is carried by a border and a background, never by colour alone. */
  .row.selected {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
  }
  .row.placing {
    border-style: dashed;
    border-color: var(--moh-accent);
  }

  .link {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
    min-height: var(--moh-tap);
    color: var(--moh-ink);
    text-decoration: none;
  }
  .link:hover .name,
  .link:focus-visible .name {
    text-decoration: underline;
  }
  .name {
    font-size: var(--moh-text-base);
  }

  .position {
    margin: var(--moh-space-1) 0 var(--moh-space-2);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
  }
</style>
