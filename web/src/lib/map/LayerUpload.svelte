<script lang="ts">
  import { Button, SelectField, TextField } from '$ui';

  /** Putting a plan or a plat into the app.
   *
   * The file input is deliberately a plain `<input type="file">` with a real
   * `<label>`: it is the one control every assistive technology and every
   * mobile browser already handles, and a prettier drop zone would be a
   * worse one.
   *
   * The two accepted formats are stated up front rather than discovered by
   * being refused, and a PDF plat gets its own sentence, because the design
   * accepts a PDF *in principle* — it is rasterised on upload — and this
   * deployment carries no rasteriser. Somebody holding a plat from the county
   * should learn that here, not from a 415.
   */
  let {
    uploading = false,
    error = null,
    operatorProblem = false,
    onupload,
  }: {
    uploading?: boolean;
    error?: string | null;
    /** True when the failure is the deployment's rather than the person's — no
     *  volume configured, or a full one. It changes the words, not the shape. */
    operatorProblem?: boolean;
    onupload?: (input: { file: File; name: string; kind: 'floor_plan' | 'survey' }) => void;
  } = $props();

  let name = $state('');
  let kind = $state<'floor_plan' | 'survey'>('floor_plan');
  let file: File | null = $state(null);
  let localError: string | null = $state(null);

  const KINDS = [
    { value: 'floor_plan', plain: 'Floor plan — a drawing of a building' },
    { value: 'survey', plain: 'Property survey — a plat of the grounds' },
  ];

  function choose(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    file = input.files?.[0] ?? null;
    localError = null;
    if (file && !name.trim()) {
      // A sensible first guess, which the person can overwrite.
      name = file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    }
  }

  function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!file) {
      localError = 'Choose an image of the plan or survey first.';
      return;
    }
    if (!name.trim()) {
      localError = 'Give the layer a name, so it can be told from the others.';
      return;
    }
    onupload?.({ file, name: name.trim(), kind });
  }
</script>

<form class="upload" onsubmit={submit} aria-labelledby="upload-heading">
  <h3 id="upload-heading">
    <span class="themed">Lodging a Plan</span>
    <span class="plain">Upload a floor plan or a property survey</span>
  </h3>

  <div class="field">
    <label class="file-label" for="layer-file">
      The image — a PNG or a JPEG
      <input
        id="layer-file"
        type="file"
        accept="image/png,image/jpeg"
        onchange={choose}
        aria-describedby="file-hint"
      />
    </label>
    <p class="hint" id="file-hint">
      A scan or a photograph works. A PDF plat has to be exported as a PNG or JPEG first — this
      deployment does not rasterise one for you.
    </p>
  </div>

  <TextField
    bind:value={name}
    plain="What to call this layer"
    themed="The name upon the plan"
    hint="Ground floor, First floor, Property survey."
    required
  />

  <SelectField bind:value={kind} options={KINDS} plain="Which kind of sheet this is" />

  <!-- `plain` only. The plain half of a paired label renders in
       `--moh-ink-muted`, which on a primary button measures 1.26:1 in
       parchment and 1.01:1 in greenhouse — invisible. Escalated to the design system; the
       themed wording is in this form's heading, at 13.4:1. -->
  <Button type="submit" plain="Upload the sheet" loading={uploading} busyPlain="Uploading…" />

  {#if localError}
    <p class="error" role="alert">{localError}</p>
  {/if}
  {#if error}
    <p class="error" role="alert" data-operator={operatorProblem}>
      {#if operatorProblem}
        <strong>This is the deployment, not the file.</strong>
      {/if}
      {error}
    </p>
  {/if}
</form>

<style>
  .upload {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-3);
    padding: var(--moh-space-4);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius-lg);
    background: var(--moh-surface-raised);
  }

  h3 {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin: 0;
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

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
  }
  .file-label {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
    font-size: var(--moh-text-base);
    color: var(--moh-ink);
  }
  input[type='file'] {
    min-height: var(--moh-tap);
    padding: var(--moh-space-2);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-field);
    color: var(--moh-ink);
    font-family: var(--moh-font-body);
  }
  input[type='file']:focus-visible {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }

  .hint {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .error {
    margin: 0;
    padding: var(--moh-space-3);
    border-radius: var(--moh-radius);
    border: 1px solid var(--moh-danger);
    color: var(--moh-danger);
    font-size: var(--moh-text-sm);
  }
</style>
