<script lang="ts">
  import { untrack } from 'svelte';
  import { Button, NumberField } from '$ui';
  import { fitSurvey, formatMetres, isCalibrated } from './projection';
  import type { CalibrationPoint, MapLayer, PixelPoint } from './types';

  /** Telling the app how big the sheet is.
   *
   * The contract carries one `Calibration` schema doing two jobs, and the
   * contract is right to: a survey derives a `scale_mm_per_px` from its
   * control points, so the field is not plan-only, and one schema is what
   * lets one component serve both map kinds. What the schema
   * cannot say is which half applies — so this panel shows one half at a
   * time, chosen by the layer's own `kind`, and the server refuses the other
   * with a 422 if anything gets past it.
   *
   * The survey half reports its own error, and reports honestly. Two points
   * fit exactly; their zero residual is a fact about arithmetic, not about
   * accuracy, and saying "0.0 m error" there would be the precise thing
   * the design warned against.
   */
  let {
    layer,
    picked = null,
    saving = false,
    error = null,
    onsave,
    onneedpick,
  }: {
    layer: MapLayer;
    /** The last point clicked on the map, waiting to be used. */
    picked?: PixelPoint | null;
    saving?: boolean;
    error?: string | null;
    onsave?: (body: { scale_mm_per_px?: number; points?: CalibrationPoint[] }) => void;
    /** Ask the host to put the map into "click a point" mode. */
    onneedpick?: () => void;
  } = $props();

  const already = $derived(isCalibrated(layer.kind, layer.calibration));

  // --- floor plan -----------------------------------------------------------
  // Seeded from the layer this panel opened on, so the server render already
  // carries the current numbers, and re-seeded below whenever the layer
  // changes — switching sheets must not leave the previous sheet's scale
  // sitting in the field looking like this one's.
  let scale = $state<number | null>(untrack(() => layer.scale_mm_per_px ?? null));
  let firstMark = $state<PixelPoint | null>(null);
  let knownMetres = $state<number | null>(null);

  const pixelSpan = $derived(
    firstMark && picked ? Math.hypot(picked.x - firstMark.x, picked.y - firstMark.y) : 0,
  );
  const measured = $derived(
    pixelSpan > 0 && knownMetres !== null && knownMetres > 0
      ? (knownMetres * 1000) / pixelSpan
      : null,
  );

  // --- survey ---------------------------------------------------------------
  let points = $state<CalibrationPoint[]>(untrack(() => copyPoints(layer)));
  let draftLat = $state<number | null>(null);
  let draftLon = $state<number | null>(null);

  const fit = $derived(fitSurvey(points));

  function copyPoints(source: MapLayer): CalibrationPoint[] {
    return (source.calibration?.points ?? []).map((point) => ({
      px: [...point.px] as [number, number],
      world: [...point.world] as [number, number],
    }));
  }

  // Re-seed on a layer change. Keyed on the id rather than the object so a
  // refetch that returns an equal layer does not wipe what is being typed.
  let seededFor = untrack(() => layer.id);
  $effect(() => {
    if (layer.id === seededFor) return;
    seededFor = layer.id;
    scale = layer.scale_mm_per_px ?? null;
    points = copyPoints(layer);
    firstMark = null;
    knownMetres = null;
    draftLat = null;
    draftLon = null;
  });

  function addPoint() {
    if (!picked || draftLat === null || draftLon === null) return;
    points = [...points, { px: [picked.x, picked.y], world: [draftLat, draftLon] }];
  }

  function removePoint(index: number) {
    points = points.filter((_, i) => i !== index);
  }
</script>

<section class="panel" aria-labelledby="calibration-heading">
  <h3 id="calibration-heading">
    <span class="themed">Taking the Measure</span>
    <span class="plain">Calibration — how big this sheet really is</span>
  </h3>

  <p class="state" data-calibrated={already}>
    {#if already}
      {layer.name} is calibrated. Changing it re-places every pin on it, because pins are stored in sheet
      pixels rather than in metres.
    {:else}
      {layer.name} is not calibrated yet. Pins can still be placed; distances and the scale bar stay unknown
      until it is.
    {/if}
  </p>

  {#if layer.kind === 'floor_plan'}
    <p class="hint">
      A floor plan is a flat drawing, so it needs one number: how many millimetres of room one pixel
      of the drawing covers.
    </p>

    <NumberField
      bind:value={scale}
      plain="Millimetres per pixel"
      themed="Rods to the pace"
      hint="A 1600-pixel plan of a 20 metre frontage is 12.5."
      min={0}
    />

    <details class="measure">
      <summary>Work it out from something you can measure</summary>
      <p class="hint">
        Click one end of a wall on the map, press <em>Mark</em>, click the other end, then type how
        long that wall really is.
      </p>
      <div class="row">
        <Button
          variant="quiet"
          plain={firstMark ? 'Re-mark the first end' : 'Mark the first end'}
          onclick={() => {
            if (!picked) onneedpick?.();
            firstMark = picked;
          }}
        />
        <span class="readout">
          {#if firstMark && picked}
            {Math.round(pixelSpan)} pixels apart
          {:else}
            No span marked yet
          {/if}
        </span>
      </div>
      <NumberField bind:value={knownMetres} plain="That distance, in metres" min={0} />
      {#if measured}
        <p class="readout">
          That works out at {measured.toFixed(2)} millimetres per pixel.
          <Button variant="quiet" plain="Use this figure" onclick={() => (scale = measured)} />
        </p>
      {/if}
    </details>

    <!-- `plain` only, deliberately. `Label.svelte` renders the plain half of a
         paired label in `--moh-ink-muted`, which on a primary button's
         `--moh-accent` background measures **1.26:1 in parchment and 1.01:1
         in greenhouse** — measured in the running app, not guessed. That is
         a defect in the design system, escalated in the pull request; it is
         not the maps module's file to fix. Here the themed wording lives in the section
         heading above, at 13.4:1, so the original-theme rule pairing holds and holds
         legibly. -->
    <Button
      plain="Save the scale"
      loading={saving}
      disabled={scale === null || scale <= 0}
      onclick={() => scale !== null && onsave?.({ scale_mm_per_px: scale })}
    />
  {:else}
    <p class="hint">
      A survey sits on the Earth, so it needs at least two points whose place you know: click a
      corner you can identify, then type its latitude and longitude.
    </p>

    <ol class="points">
      {#each points as point, index (index)}
        <li>
          <span class="readout">
            Point {index + 1}: pixel {Math.round(point.px[0])}, {Math.round(point.px[1])}
            → {point.world[0].toFixed(6)}, {point.world[1].toFixed(6)}
          </span>
          <Button
            variant="quiet"
            plain={`Remove point ${index + 1}`}
            onclick={() => removePoint(index)}
          />
        </li>
      {/each}
    </ol>

    <div class="draft">
      <p class="readout">
        {#if picked}
          Picked pixel {Math.round(picked.x)}, {Math.round(picked.y)}
        {:else}
          Click the map to pick a pixel for the next point.
        {/if}
      </p>
      <NumberField bind:value={draftLat} plain="Latitude, in degrees" step={0.000001} />
      <NumberField bind:value={draftLon} plain="Longitude, in degrees" step={0.000001} />
      <Button
        variant="quiet"
        plain="Add this point"
        disabled={!picked || draftLat === null || draftLon === null}
        onclick={addPoint}
      />
    </div>

    {#if fit}
      <p class="fit">
        <strong>{formatMetres(fit.metresPerPx)} per pixel</strong>, turned
        {fit.rotationDeg.toFixed(1)}° from north.
        {#if fit.residualIsMeaningful}
          The {fit.pointCount} points agree to within {formatMetres(fit.rmsErrorM)} on average, {formatMetres(
            fit.worstErrorM,
          )} at worst.
        {:else}
          Two points always fit exactly, so nothing here measures how accurate the overlay is. Add a
          third point you can identify to find out.
        {/if}
      </p>
    {:else}
      <p class="fit">
        {points.length} of the two points a survey needs.
      </p>
    {/if}

    <!-- `plain` only: see the note on the floor-plan button above. -->
    <Button
      plain="Save the control points"
      loading={saving}
      disabled={points.length < 2}
      onclick={() => onsave?.({ points })}
    />
  {/if}

  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}
</section>

<style>
  .panel {
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

  .state,
  .hint,
  .readout,
  .fit {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .fit,
  .readout {
    color: var(--moh-ink);
  }
  /* Calibrated or not is said in words above; the rule is a second, non-colour
     signal rather than the only one. */
  .state[data-calibrated='false'] {
    border-left: 3px solid var(--moh-parched);
    padding-left: var(--moh-space-3);
  }
  .state[data-calibrated='true'] {
    border-left: 3px solid var(--moh-thriving);
    padding-left: var(--moh-space-3);
  }

  .points {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
  }
  .points li,
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--moh-space-2);
  }

  .draft,
  .measure {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
    padding: var(--moh-space-3);
    border: 1px dashed var(--moh-border);
    border-radius: var(--moh-radius);
  }
  summary {
    cursor: pointer;
    min-height: var(--moh-tap);
    display: flex;
    align-items: center;
    color: var(--moh-accent);
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
