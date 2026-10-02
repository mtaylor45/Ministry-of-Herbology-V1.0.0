<script lang="ts">
  /** Where this picture came from, next to the picture.
   *
   *  This component is the releases's whole argument in one place. The house
   *  style asks for a hand-coloured lithograph on aged cream paper, and an
   *  image that meets that brief and was generated last Tuesday is a
   *  fabricated historical artefact unless the reader is told — so the telling
   *  cannot be optional, cannot be hidden, and cannot be a hover.
   *
   *  the design settled the shape for task certainty: *next to the instruction,
   *  not behind a tooltip.* A book view's "next to the instruction" is on the
   *  plate, in the flow, above the fold of the caption. So:
   *
   *  - a generated plate gets a **marked** note with a visible border and an
   *    icon, always rendered, never collapsed;
   *  - status is never carried by colour alone — the word "Drawn to
   *    order" and the plain sentence do the work, and the colour agrees with
   *    them rather than replacing them;
   *  - the same sentence is inside the plate's `alt` text (`plates.ts`), so a
   *    reader who cannot see this note is not told less than one who can.
   *
   *  A collected plate's note carries its licence and credit. A generated one
   *  has neither, by construction, so there is nothing to put beside the
   *  warning and nothing is invented to fill the space.
   */
  import { Icon, Label } from '$ui';
  import type { Plate } from './api';
  import { provenanceOf } from './plates';

  let { plate }: { plate: Plate } = $props();

  const provenance = $derived(provenanceOf(plate));
</script>

<div class="note" data-kind={provenance.kind}>
  <span class="glyph" aria-hidden="true">
    <Icon name={provenance.kind === 'drawn' ? 'warning' : 'quill'} size={18} strokeWidth={1.6} />
  </span>
  <div class="text">
    <p class="head">
      <Label
        themed={provenance.themed}
        plain={provenance.plain}
        display="below"
        where="ProvenanceNote"
      />
    </p>
    {#if provenance.credit}
      <p class="credit">{provenance.credit}</p>
    {:else if provenance.kind === 'drawn'}
      <!-- Said out loud rather than left as an empty row: a blank credit line
           under a nineteenth-century-looking picture reads as "uncredited
           antique", which is the misreading this whole note exists to stop. -->
      <p class="credit">
        It carries no licence and no attribution, because there is no collection or artist to
        credit.
      </p>
    {/if}
  </div>
</div>

<style>
  .note {
    display: flex;
    gap: var(--moh-space-3);
    align-items: flex-start;
    padding: var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
    color: var(--moh-ink);
  }

  /* A generated plate's note is the loud one. Border weight and an icon, not
     colour alone — the words carry the meaning. */
  .note[data-kind='drawn'] {
    border-width: 2px;
    border-color: var(--moh-parched);
    background: var(--moh-surface-raised);
  }

  .glyph {
    display: inline-flex;
    flex: none;
    margin-top: 2px;
    color: var(--moh-ink);
  }

  .note[data-kind='drawn'] .glyph {
    color: var(--moh-parched);
  }

  .text {
    display: grid;
    gap: var(--moh-space-1);
    min-width: 0;
  }

  .head {
    margin: 0;
  }

  .credit {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
    overflow-wrap: anywhere;
  }
</style>
