<script lang="ts">
  /** The Naturalist's Journal for one plant.
   *
   *  The same leaf the book view shows, plus this plant's field notes. It
   *  reuses `PlatePage.svelte` rather than restating the plate markup, so the
   *  provenance label cannot end up correct in one place and missing in the
   *  other — which is exactly how a generated plate would quietly lose its
   *  label on one of two screens.
   */
  import { Card } from '$ui';
  import { invalidateAll } from '$app/navigation';
  import FieldNotes from '../FieldNotes.svelte';
  import PlatePage from '../PlatePage.svelte';
  import { reason, writes } from '../api';
  import { buildPages, coverageBySpecimen } from '../plates';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const specimen = $derived(data.specimen.value);
  const members = $derived(data.members.value ?? []);
  const page = $derived(
    specimen ? (buildPages([specimen], data.plates.value ?? [])[0] ?? null) : null,
  );

  const coverageEntry = $derived(coverageBySpecimen(data.coverage.value).get(data.specimenId));

  let approving = $state<string | null>(null);
  let approvalError = $state<string | null>(null);

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
      await invalidateAll();
    } catch (cause) {
      approvalError = reason(cause);
    } finally {
      approving = null;
    }
  }
</script>

<svelte:head>
  <title>
    {specimen ? `${specimen.display_name} — Journal` : 'Journal'} — The Ministry of Herbology
  </title>
</svelte:head>

<div class="facet">
  {#if data.specimen.error}
    <Card themed="This plant is out of reach" plain="Could not load the plant" level={2}>
      <p class="problem">{data.specimen.error}</p>
    </Card>
  {:else if page}
    <Card themed="The plate" plain="This plant's illustration" level={2}>
      {#if data.plates.error}
        <p class="problem">
          {data.plates.error} The plate cannot be shown, which is not the same as there being none — the
          field notes below are unaffected.
        </p>
      {:else}
        <PlatePage
          {page}
          coverage={coverageEntry}
          approving={approving === page.plate?.id}
          canApprove={Boolean(members.length)}
          onapprove={approve}
        />
      {/if}
      {#if approvalError}
        <p class="problem" role="alert">{approvalError}</p>
      {/if}
    </Card>

    <FieldNotes
      specimenId={data.specimenId}
      notes={data.notes.value ?? []}
      {members}
      error={data.notes.error}
      oncreated={invalidateAll}
    />

    <p class="back">
      <a href="/journal?plant={data.specimenId}">Open this leaf in the whole journal</a>
    </p>
  {/if}
</div>

<style>
  .facet {
    display: grid;
    gap: var(--moh-space-6);
    padding: var(--moh-space-4);
    max-width: 44rem;
    margin: 0 auto;
  }

  .problem {
    margin: 0;
    color: var(--moh-ink);
  }

  .back {
    margin: 0;
  }

  .back a {
    color: var(--moh-ink);
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .back a:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
</style>
