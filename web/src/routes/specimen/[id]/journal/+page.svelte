<script lang="ts">
  /** Naturalist's Journal — the fourth facet: this plant's plate, where the
   *  plate came from, the household's field notes, and the photo growth log.
   *
   *  The plate and the notes are the journal's components, rendered here
   *  rather than linked to. A facet that is only a link to another page is not
   *  a facet, and this page is where a person stands when they want to see
   *  their plant's plate. Rendering the journal's `PlatePage` rather than restating its
   *  markup is also what keeps three things true that the whole releases turns
   *  on:
   *
   *  - a plate is never shown without its `ProvenanceNote`, beside it, never
   *    collapsed and never behind a tap — `PlatePage` renders the note itself;
   *  - the plate's `alt` text is the journal's `altTextFor()`, so a reader who cannot see
   *    the note is told no less than one who can;
   *  - a plate nobody has accepted is shown and marked as waiting, and a plant
   *    with no plate gets the journal's `absenceSentence()` on a named blank leaf, never
   *    a placeholder picture.
   *
   *  Accepting a plate is the same act it is in the book: The journal's route, the first
   *  recorded member as the approver (the journal's escalation, left as the journal left it — a
   *  proper member picker belongs with the contract line the design declares).
   */
  import { invalidate } from '$app/navigation';
  import { Card, StaleNotice } from '$ui';
  import type { PageData } from './$types';
  import FieldNotes from '../../../journal/FieldNotes.svelte';
  import PlatePage from '../../../journal/PlatePage.svelte';
  import { reason, writes } from '../../../journal/api';
  import SeeAlso from '../SeeAlso.svelte';
  import GrowthLog from './GrowthLog.svelte';
  import { leafFor } from './journalFacet';

  let { data }: { data: PageData } = $props();

  const specimen = $derived(data.specimen);
  const members = $derived(data.members.value ?? []);
  const leaf = $derived(leafFor(specimen, data.plates.value ?? []));

  let approving = $state<string | null>(null);
  let approvalError = $state<string | null>(null);

  function refresh() {
    void invalidate('moh:specimen');
  }

  async function approve(plateId: string) {
    const member = members[0];
    if (!member) {
      approvalError =
        'No household member is recorded, and a plate is accepted by somebody — so there is nobody to record as having accepted it.';
      return;
    }
    approving = plateId;
    approvalError = null;
    try {
      await writes.approve(plateId, member.id, fetch);
      refresh();
    } catch (cause) {
      approvalError = reason(cause);
    } finally {
      approving = null;
    }
  }
</script>

<div class="stack">
  <Card themed="The plate" plain="This plant's illustration, and where it came from" level={2}>
    {#if data.plates.error}
      <!-- A failed read is not an absent plate. The stale notice says which,
           so the reader is not told "no plate" by a timeout. -->
      <StaleNotice plain="The plate" asOf={null} reason={data.plates.error} />
    {:else}
      <PlatePage
        page={leaf}
        approving={approving === leaf.plate?.id}
        canApprove={Boolean(members.length)}
        onapprove={approve}
      />
    {/if}
    {#if approvalError}
      <p class="problem" role="alert">{approvalError}</p>
    {/if}
    <p class="aside">
      <a href="/journal?plant={specimen.id}">Open this leaf in the whole journal</a>, where the book
      pages through every plant in the Register.
    </p>
  </Card>

  <FieldNotes
    specimenId={specimen.id}
    notes={data.notes.value ?? []}
    {members}
    error={data.notes.error}
    oncreated={refresh}
  />

  <GrowthLog
    photos={data.photos.value ?? []}
    specimenName={specimen.display_name}
    error={data.photos.error}
    specimenId={specimen.id}
    {members}
    onuploaded={refresh}
  />

  <SeeAlso current="journal" specimenId={specimen.id} />
</div>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }

  .problem {
    margin: var(--moh-space-3) 0 0;
    color: var(--moh-ink);
  }

  .aside {
    margin: var(--moh-space-4) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .aside a {
    color: var(--moh-ink);
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .aside a:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
</style>
