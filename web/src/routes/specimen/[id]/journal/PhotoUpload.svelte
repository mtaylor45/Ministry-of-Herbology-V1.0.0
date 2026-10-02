<script lang="ts">
  /** Add a photograph to this plant's growth log: a PNG or JPEG, an optional
   *  caption, and who took it (`MemberPicker`, the design — the record says who).
   *
   *  The control replaces the old "photographs cannot be added from here yet"
   *  now that the inventory API's route is real. On success the facet re-reads, so the
   *  log shows what the server kept rather than what the browser hoped.
   */
  import { Button, MemberPicker, TextField, type Member } from '$ui';
  import { UploadRefused, uploadPhoto } from './photoUpload';

  let {
    specimenId,
    specimenName,
    members,
    onuploaded,
  }: {
    specimenId: string;
    specimenName: string;
    members: Member[];
    onuploaded?: () => void;
  } = $props();

  const inputId = $derived(`photo-file-${specimenId}`);
  let fileInput = $state<HTMLInputElement | null>(null);
  let file = $state<File | null>(null);
  let caption = $state('');
  let memberId = $state('');
  let busy = $state(false);
  let problem = $state<string | null>(null);
  let done = $state<string | null>(null);

  function picked(event: Event) {
    const files = (event.currentTarget as HTMLInputElement).files;
    file = files && files.length ? files[0] : null;
    problem = null;
    done = null;
  }

  async function send(event: SubmitEvent) {
    event.preventDefault();
    if (!file) {
      problem = 'Choose a photograph first.';
      fileInput?.focus();
      return;
    }
    busy = true;
    problem = null;
    done = null;
    try {
      await uploadPhoto(specimenId, { file, caption, memberId }, fetch);
      done = `Photograph added to ${specimenName}’s growth log.`;
      caption = '';
      file = null;
      if (fileInput) fileInput.value = '';
      onuploaded?.();
    } catch (cause) {
      problem =
        cause instanceof UploadRefused
          ? cause.message
          : 'The photograph could not be sent — the connection may have dropped. Try again.';
    } finally {
      busy = false;
    }
  }
</script>

<form class="upload" onsubmit={send}>
  <h3>Add a photograph</h3>
  <div class="file">
    <label for={inputId}>Photograph <span class="hint">(PNG or JPEG)</span></label>
    <input
      id={inputId}
      bind:this={fileInput}
      type="file"
      name="file"
      accept="image/png,image/jpeg"
      onchange={picked}
      aria-describedby={problem ? `${inputId}-problem` : undefined}
    />
  </div>
  <TextField
    name="caption"
    plain="Caption (optional)"
    themed="What the likeness shows"
    hint="What is new — a first flower, a new leaf, a pest."
    bind:value={caption}
  />
  <MemberPicker {members} bind:value={memberId} themed="Whose eye" plain="Who took it" />
  <Button
    type="submit"
    themed="Take a likeness"
    plain="Add the photograph"
    icon="camera"
    loading={busy}
    busyPlain="Sending the photograph…"
  />
  <p class="status" role="status">{done ?? ''}</p>
  {#if problem}<p class="problem" id="{inputId}-problem" role="alert">{problem}</p>{/if}
</form>

<style>
  .upload {
    display: grid;
    gap: var(--moh-space-3);
    margin-top: var(--moh-space-6);
    padding-top: var(--moh-space-4);
    border-top: 1px solid var(--moh-border);
  }
  h3 {
    margin: 0;
    font-size: var(--moh-text-lg);
  }
  .file {
    display: grid;
    gap: var(--moh-space-1);
  }
  label {
    font-weight: 600;
  }
  .hint {
    font-weight: normal;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  input[type='file'] {
    min-height: var(--moh-tap);
    padding: var(--moh-space-2);
    color: var(--moh-ink);
    background: var(--moh-field);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    font-family: var(--moh-font-ui);
    max-width: 100%;
  }
  input[type='file']:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .status,
  .problem {
    margin: 0;
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .status {
    color: var(--moh-ink-muted);
  }
  .problem {
    color: var(--moh-ink);
    font-weight: 600;
  }
</style>
