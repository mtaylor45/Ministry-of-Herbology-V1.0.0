<script lang="ts">
  import { untrack } from 'svelte';
  import { Button, EmptyState } from '$ui';
  import CalibrationPanel from './CalibrationPanel.svelte';
  import GroundsMap from './GroundsMap.svelte';
  import LayerUpload from './LayerUpload.svelte';
  import PinList from './PinList.svelte';
  import * as grounds from './client';
  import { GroundsError, isOperatorProblem } from './client';
  import { pinRows, type PinRow } from './pins';
  import type { CalibrationPoint, MapLayer, Pin, PixelPoint, Zone } from './types';

  /** The whole Grounds surface, assembled.
   *
   * The app's screens owns `web/src/routes/` and takes the Specimen cross-links
   * after this release. So that the app's screens is never blocked on the maps module, everything
   * needed for `/grounds` is here behind one component: The app's screens' route can be
   * `<Grounds />` and nothing more, and the cross-link work is then about
   * the Specimen side rather than about rebuilding this.
   *
   * State lives here rather than in the map, because the list and the map
   * must never disagree: one array of rows, one selection, one placement
   * mode, rendered twice.
   */
  let {
    layers = [],
    pins = [],
    zones = [],
  }: { layers?: MapLayer[]; pins?: Pin[]; zones?: Zone[] } = $props();

  // Seeded once from the props, then owned here: every write below goes
  // through the API and comes back, so the props are a starting point rather
  // than a live source. `untrack` says that deliberately instead of leaving
  // it to look like a mistake.
  let allLayers = $state<MapLayer[]>(untrack(() => layers));
  let allPins = $state<Pin[]>(untrack(() => pins));
  let allZones = $state<Zone[]>(untrack(() => zones));

  let activeId = $state<string | null>(untrack(() => layers[0]?.id ?? null));
  let selectedId = $state<string | null>(null);
  let placingRow = $state<PinRow | null>(null);
  let picked = $state<PixelPoint | null>(null);

  let uploading = $state(false);
  let uploadError = $state<string | null>(null);
  let uploadIsOperators = $state(false);
  let saving = $state(false);
  let calibrationError = $state<string | null>(null);
  let pinError = $state<string | null>(null);
  let note = $state('');

  const active = $derived(allLayers.find((layer) => layer.id === activeId) ?? allLayers[0] ?? null);
  const rows = $derived(active ? pinRows(active, allPins) : []);

  async function refreshPins() {
    allPins = await grounds.listPins();
  }

  async function handleUpload(input: { file: File; name: string; kind: 'floor_plan' | 'survey' }) {
    uploading = true;
    uploadError = null;
    uploadIsOperators = false;
    try {
      const created = await grounds.uploadLayer(input);
      allLayers = [...allLayers, created];
      activeId = created.id;
      note = `${created.name} is up, ${created.image_width_px} by ${created.image_height_px} pixels. It is not calibrated yet.`;
    } catch (error) {
      uploadError = error instanceof GroundsError ? error.detail : String(error);
      uploadIsOperators = isOperatorProblem(error);
    } finally {
      uploading = false;
    }
  }

  async function handleCalibration(body: {
    scale_mm_per_px?: number;
    points?: CalibrationPoint[];
  }) {
    if (!active) return;
    saving = true;
    calibrationError = null;
    try {
      const updated = await grounds.setCalibration(active.id, body);
      allLayers = allLayers.map((layer) => (layer.id === updated.id ? updated : layer));
      note = `${updated.name} is calibrated. Every pin on it has been re-placed against the new measure.`;
    } catch (error) {
      calibrationError = error instanceof GroundsError ? error.detail : String(error);
    } finally {
      saving = false;
    }
  }

  async function commitPin(px: PixelPoint) {
    if (!active || !placingRow) return;
    pinError = null;
    const row = placingRow;
    try {
      await grounds.setPin({ specimen_id: row.specimenId, layer_id: active.id, px });
      await refreshPins();
      note = `${row.name} is pinned to ${active.name}.`;
      placingRow = null;
      selectedId = row.specimenId;
    } catch (error) {
      pinError = error instanceof GroundsError ? error.detail : String(error);
    }
  }

  async function liftPin(row: PinRow) {
    if (!active) return;
    pinError = null;
    try {
      await grounds.setPin({ specimen_id: row.specimenId, layer_id: active.id, px: null });
      await refreshPins();
      note = `${row.name} is off the map. It is still in the Register.`;
    } catch (error) {
      pinError = error instanceof GroundsError ? error.detail : String(error);
    }
  }
</script>

<div class="grounds">
  <header>
    <h2>
      <span class="themed">The Grounds</span>
      <span class="plain">Maps of the house and the land</span>
    </h2>
  </header>

  {#if allLayers.length === 0}
    <EmptyState
      icon="pin"
      themed="No plans are lodged"
      plain="No maps yet"
      body="Upload a floor plan or a property survey and the plants can be placed on it."
    />
  {:else}
    <nav class="layers" aria-label="Map layers">
      <ul>
        {#each allLayers as layer (layer.id)}
          <li>
            <Button
              variant={layer.id === active?.id ? 'primary' : 'quiet'}
              plain={layer.name}
              onclick={() => {
                activeId = layer.id;
                placingRow = null;
                picked = null;
              }}
              aria-current={layer.id === active?.id ? 'true' : undefined}
            />
          </li>
        {/each}
      </ul>
    </nav>
  {/if}

  {#if active}
    <GroundsMap
      layer={active}
      {rows}
      zones={allZones.filter((zone) => zone.map_layer_id === active.id)}
      {selectedId}
      {placingRow}
      oncommit={commitPin}
      oncancel={() => (placingRow = null)}
      onpick={(px) => (picked = px)}
      onzonedrawn={(boundary) => {
        note = `A zone of ${boundary.length} corners is drawn. It cannot be saved yet — see the note below.`;
      }}
    />

    {#if pinError}
      <p class="error" role="alert">{pinError}</p>
    {/if}

    <PinList
      layer={active}
      {rows}
      {selectedId}
      placingId={placingRow?.specimenId ?? null}
      onplace={(row) => (placingRow = placingRow?.specimenId === row.specimenId ? null : row)}
      onlift={liftPin}
      onhighlight={(row) => (selectedId = row?.specimenId ?? null)}
    />

    <CalibrationPanel
      layer={active}
      {picked}
      {saving}
      error={calibrationError}
      onsave={handleCalibration}
    />
  {/if}

  <LayerUpload
    {uploading}
    error={uploadError}
    operatorProblem={uploadIsOperators}
    onupload={handleUpload}
  />

  <p class="live" role="status" aria-live="polite">{note}</p>
</div>

<style>
  .grounds {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-6);
    padding: var(--moh-space-4);
  }

  h2 {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin: 0;
  }
  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-2xl);
    color: var(--moh-ink);
  }
  .plain {
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .layers ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
  }

  .error {
    margin: 0;
    padding: var(--moh-space-3);
    border-radius: var(--moh-radius);
    border: 1px solid var(--moh-danger);
    color: var(--moh-danger);
    font-size: var(--moh-text-sm);
  }

  .live {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
    min-height: 1.4em;
  }
</style>
