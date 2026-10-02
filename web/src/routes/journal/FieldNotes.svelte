<script lang="ts">
  /** This plant's field notes, and a box to write another.
   *
   *  A note is somebody's observation, so two things matter beyond the text:
   *
   *  - **who wrote it.** the design gives the household one shared sign-in and
   *    picks the member at the moment of writing, which is why there is a
   *    picker here rather than an assumed author. The frozen request body has
   *    no field for a member, so this sends one additively and the pull
   *    request asks A for the contract line — see `api.ts`.
   *  - **that a failed write is visible.** A note that silently fails is worse
   *    than one that refuses: the writer walks away believing the observation
   *    is recorded. The textarea keeps its text on failure.
   *
   *  A note whose author was never recorded renders as "author not recorded"
   *  rather than as a blank, because the API omits `written_by` instead of
   *  serving null and an empty byline reads as nobody having checked.
   */
  import { Button, Card, EmptyState, Field, SelectField } from '$ui';
  import { reason, writes, type FieldNote, type Member } from './api';

  let {
    specimenId,
    notes,
    members,
    error = null,
    oncreated,
  }: {
    specimenId: string;
    notes: FieldNote[];
    members: Member[];
    error?: string | null;
    oncreated?: () => void;
  } = $props();

  let draft = $state('');
  let author = $state('');
  let saving = $state(false);
  let problem = $state<string | null>(null);

  const authorOptions = $derived([
    { value: '', plain: 'Not recorded' },
    ...members.map((member) => ({ value: member.id, plain: member.name })),
  ]);

  const draftId = $props.id();

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    const body = draft.trim();
    if (!body) {
      problem = 'A field note needs something in it.';
      return;
    }
    saving = true;
    problem = null;
    try {
      await writes.note(specimenId, body, fetch, author || undefined);
      draft = '';
      oncreated?.();
    } catch (cause) {
      // The draft is deliberately kept: see the note above.
      problem = reason(cause);
    } finally {
      saving = false;
    }
  }

  function when(note: FieldNote): string {
    const at = new Date(note.written_at);
    return Number.isNaN(at.getTime())
      ? note.written_at
      : at.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }
</script>

<Card themed="Field notes" plain="What the household has observed" level={2}>
  {#if error}
    <p class="problem">{error}</p>
  {:else if !notes.length}
    <EmptyState
      icon="quill"
      themed="An unmarked page"
      plain="No field notes yet"
      body="Anything you notice about this plant goes here, with the date and who saw it."
    />
  {:else}
    <ol class="notes">
      {#each notes as note (note.id)}
        <li class="note">
          <p class="body">{note.body}</p>
          <p class="byline">
            <time datetime={note.written_at}>{when(note)}</time>
            <span aria-hidden="true">·</span>
            {#if note.written_by}
              <span>{note.written_by.name}</span>
            {:else}
              <span class="unrecorded">Author not recorded</span>
            {/if}
          </p>
        </li>
      {/each}
    </ol>
  {/if}

  <form class="write" onsubmit={submit}>
    <Field
      id={draftId}
      themed="A new entry"
      plain="Add a note"
      hint="Dated automatically. Say what you saw, not what it means."
    >
      {#snippet children({ describedBy })}
        <textarea
          id={draftId}
          bind:value={draft}
          rows="3"
          aria-describedby={describedBy}
          placeholder="New leaf unfurling on the north side…"
          disabled={saving}
        ></textarea>
      {/snippet}
    </Field>
    <div class="row">
      <SelectField
        themed="Whose eyes"
        plain="Who saw it"
        options={authorOptions}
        bind:value={author}
        disabled={saving || !members.length}
      />
      <Button
        variant="primary"
        type="submit"
        themed="Set it down"
        plain="Write it down"
        loading={saving}
        busyPlain="Writing the note…"
      />
    </div>
    {#if problem}
      <p class="problem" role="alert">{problem}</p>
    {/if}
  </form>
</Card>

<style>
  .notes {
    list-style: none;
    margin: 0 0 var(--moh-space-4);
    padding: 0;
    display: grid;
    gap: var(--moh-space-4);
  }

  .note {
    border-left: 2px solid var(--moh-gold-line);
    padding-left: var(--moh-space-3);
  }

  .body {
    margin: 0 0 var(--moh-space-1);
    color: var(--moh-ink);
  }

  .byline {
    margin: 0;
    display: flex;
    gap: var(--moh-space-2);
    flex-wrap: wrap;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .unrecorded {
    font-style: italic;
  }

  .write {
    display: grid;
    gap: var(--moh-space-3);
    border-top: 1px solid var(--moh-border);
    padding-top: var(--moh-space-4);
  }

  textarea {
    font: inherit;
    color: var(--moh-ink);
    background: var(--moh-field);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    padding: var(--moh-space-3);
    min-height: var(--moh-tap);
    resize: vertical;
    width: 100%;
    box-sizing: border-box;
  }

  textarea:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }

  .row {
    display: flex;
    gap: var(--moh-space-3);
    align-items: flex-end;
    flex-wrap: wrap;
  }

  .problem {
    margin: 0;
    color: var(--moh-ink);
  }
</style>
