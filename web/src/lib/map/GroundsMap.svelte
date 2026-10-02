<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { PinRow } from './pins';
  import { layerSummary, quadrantOf } from './pins';
  import { isArrow, movementAnnouncement, nudge, round, startingPoint } from './placement';
  import { clampToLayer, millimetresPerPixel, scaleBar } from './projection';
  import type { MapLayer, PixelPoint, Zone } from './types';

  /** The Leaflet surface: one component for both map kinds, as the design asked.
   *
   * A floor plan and a property survey differ in what their calibration
   * *means*, not in how they are drawn — pins live in layer pixels either way
   *, so recalibrating moves every pin correctly and a plan needs
   * no fiction about where on Earth it sits. Both therefore render on
   * `CRS.Simple` over an image overlay, and the georeferencing shows up in
   * the scale bar and the readouts rather than in a second map.
   *
   * Leaflet is imported inside `onMount`. It touches `window` at module
   * scope, and this component has to server-render: the list beside it is the
   * accessible equivalent of the pins, and an equivalent that only exists
   * after hydration is not one.
   */
  let {
    layer,
    rows = [],
    zones = [],
    selectedId = null,
    placingRow = null,
    height = '60vh',
    oncommit,
    oncancel,
    onpick,
    onzonedrawn,
  }: {
    layer: MapLayer;
    rows?: PinRow[];
    zones?: Zone[];
    selectedId?: string | null;
    /** Non-null puts the map in placement mode for that plant. */
    placingRow?: PinRow | null;
    height?: string;
    oncommit?: (px: PixelPoint) => void;
    oncancel?: () => void;
    /** A bare click on the sheet, outside placement mode. */
    onpick?: (px: PixelPoint) => void;
    onzonedrawn?: (boundary: [number, number][]) => void;
  } = $props();

  let host: HTMLDivElement | null = $state(null);
  let ready = $state(false);
  let announcement = $state('');
  let bar: { metres: number; widthPx: number } | null = $state(null);
  let drawing: [number, number][] = $state([]);
  let drawMode = $state(false);
  let crosshair: PixelPoint | null = $state(null);

  // Leaflet's own types are not installed, and adding a dependency for four
  // call sites is not a trade worth making. The surface used is small and is
  // named here so it is at least written down.
  /* eslint-disable @typescript-eslint/no-explicit-any */
  let L: any = null;
  let map: any = null;
  let overlay: any = null;
  let markerLayer: any = null;
  let zoneLayer: any = null;
  let drawLayer: any = null;
  let crosshairMarker: any = null;

  /** `CRS.Simple` counts y upward and an image counts it downward, so the
   *  whole sheet lives at negative latitude and the flip happens here, once. */
  const toLatLng = (px: PixelPoint) => [-px.y, px.x] as [number, number];
  const fromLatLng = (latlng: { lat: number; lng: number }): PixelPoint =>
    round({ x: latlng.lng, y: -latlng.lat });

  const summary = $derived(layerSummary(layer, rows));
  const placing = $derived(placingRow !== null);

  onMount(async () => {
    await import('leaflet/dist/leaflet.css');
    L = (await import('leaflet')).default;
    if (!host) return;

    map = L.map(host, {
      crs: L.CRS.Simple,
      minZoom: -5,
      maxZoom: 4,
      // Fractional zoom. Leaflet snaps to whole zoom levels by default, and
      // a whole level is a factor of two: a 1600px plan in a 343px column
      // lands at 200px and leaves two thirds of the map empty. On a phone
      // that is most of the screen given to nothing.
      zoomSnap: 0,
      zoomControl: true,
      attributionControl: false,
      // The map is one tab stop; the pins are reached through the list, which
      // is the whole accessibility argument. Leaflet's own keyboard panning
      // stays on, so the sheet can still be moved without a pointer.
      keyboard: true,
    });

    markerLayer = L.layerGroup().addTo(map);
    zoneLayer = L.layerGroup().addTo(map);
    drawLayer = L.layerGroup().addTo(map);

    map.on('click', (event: any) => {
      const px = clampToLayer(layer, fromLatLng(event.latlng));
      if (drawMode) {
        drawing = [...drawing, [px.x, px.y]];
        redrawDrawing();
        return;
      }
      if (placing) {
        crosshair = px;
        oncommit?.(px);
        return;
      }
      onpick?.(px);
    });
    map.on('zoomend moveend', updateScaleBar);

    ready = true;
    drawLayerImage();
    updateScaleBar();
  });

  onDestroy(() => {
    map?.remove?.();
    map = null;
  });

  function drawLayerImage() {
    if (!map || !L) return;
    const bounds = [
      [-layer.image_height_px, 0],
      [0, layer.image_width_px],
    ];
    overlay?.remove?.();
    overlay = L.imageOverlay(layer.image_url, bounds, {
      alt: `${layer.name}, a ${layer.kind === 'floor_plan' ? 'floor plan' : 'property survey'}`,
    }).addTo(map);
    map.fitBounds(bounds, { padding: [6, 6] });
  }

  function updateScaleBar() {
    if (!map) return;
    const mmPerPx = millimetresPerPixel(layer);
    if (mmPerPx === null) {
      bar = null;
      return;
    }
    // One screen pixel at this zoom covers this many layer pixels.
    const layerPxPerScreenPx = 1 / 2 ** map.getZoom();
    bar = scaleBar((layerPxPerScreenPx * mmPerPx) / 1000);
  }

  function redrawMarkers() {
    if (!ready || !markerLayer || !L) return;
    markerLayer.clearLayers();
    for (const row of rows) {
      if (!row.px) continue;
      const selected = row.specimenId === selectedId;
      const marker = L.marker(toLatLng(row.px), {
        keyboard: true,
        title: row.label,
        alt: row.label,
        icon: L.divIcon({
          className: 'moh-pin',
          html: `<span class="moh-pin-dot${selected ? ' is-selected' : ''}"></span>`,
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        }),
      });
      // A marker is a positioned div; without this it is a shape with no name.
      marker.on('add', () => {
        const element = marker.getElement();
        if (!element) return;
        element.setAttribute('role', 'link');
        element.setAttribute('aria-label', row.label);
      });
      marker.on('click', () => {
        window.location.assign(row.href);
      });
      marker.addTo(markerLayer);
    }
  }

  function redrawZones() {
    if (!ready || !zoneLayer || !L) return;
    zoneLayer.clearLayers();
    for (const zone of zones) {
      if (!zone.boundary_px?.length) continue;
      L.polygon(
        zone.boundary_px.map(([x, y]) => toLatLng({ x, y })),
        { className: 'moh-zone', weight: 2, fillOpacity: 0.12 },
      )
        .bindTooltip(zone.name, { permanent: false })
        .addTo(zoneLayer);
    }
  }

  function redrawDrawing() {
    if (!ready || !drawLayer || !L) return;
    drawLayer.clearLayers();
    if (drawing.length < 2) return;
    L.polyline(
      drawing.map(([x, y]) => toLatLng({ x, y })),
      { className: 'moh-zone-draft', weight: 2, dashArray: '6 4' },
    ).addTo(drawLayer);
  }

  function redrawCrosshair() {
    if (!ready || !L || !map) return;
    crosshairMarker?.remove?.();
    crosshairMarker = null;
    if (!placing || !crosshair) return;
    crosshairMarker = L.marker(toLatLng(crosshair), {
      keyboard: false,
      icon: L.divIcon({
        className: 'moh-crosshair',
        html: '<span class="moh-crosshair-mark"></span>',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      }),
    }).addTo(map);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (!placing || !crosshair) return;
    if (isArrow(event.key)) {
      event.preventDefault();
      crosshair = nudge(layer, crosshair, event.key, event.shiftKey);
      announcement = movementAnnouncement(layer, crosshair, quadrantOf);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      oncommit?.(crosshair);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      oncancel?.();
    }
  }

  function toggleDrawMode() {
    drawMode = !drawMode;
    if (!drawMode && drawing.length >= 3) {
      onzonedrawn?.(drawing);
    }
    if (!drawMode) {
      drawing = [];
      redrawDrawing();
    }
  }

  // Redraws follow the props, so the map cannot fall behind the list.
  $effect(() => {
    void rows;
    void selectedId;
    redrawMarkers();
  });
  $effect(() => {
    void zones;
    redrawZones();
  });
  $effect(() => {
    void layer;
    if (ready) {
      drawLayerImage();
      updateScaleBar();
    }
  });
  $effect(() => {
    if (placing && !crosshair) {
      crosshair = startingPoint(layer, placingRow?.px ?? null);
      announcement = `Placing ${placingRow?.name}. ${movementAnnouncement(layer, crosshair, quadrantOf)}. Arrow keys move it, Enter places it, Escape stops.`;
    }
    if (!placing) crosshair = null;
    redrawCrosshair();
  });
</script>

<div class="wrap">
  <p class="summary" id="map-summary">{summary}</p>

  <!--
    `role="application"` on a focusable div is what a map widget is: it tells a
    screen reader to stop intercepting arrow keys and hand them to the
    component, which is the whole of keyboard pin placement. Svelte's rule
    counts the role as non-interactive and so objects to the tabindex; the
    role is only any use if it can take focus, so the rule is waived here
    rather than the role dropped.

    This is also why the pin list beside the map is shown and not hidden:
    `application` is a heavy hammer, and the list is the route that works
    without it.
  -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div
    bind:this={host}
    class="canvas"
    class:placing
    style:height
    role="application"
    tabindex="0"
    aria-label={`Map of ${layer.name}`}
    aria-describedby="map-summary"
    onkeydown={handleKeydown}
  ></div>

  <div class="under">
    {#if bar}
      <div class="scale" aria-hidden="true">
        <span class="bar" style:width={`${Math.round(bar.widthPx)}px`}></span>
        <span class="bar-label">{bar.metres} m</span>
      </div>
      <p class="visually-hidden">
        The scale bar shows {bar.metres} metres.
      </p>
    {:else}
      <p class="uncal">
        {layer.name} is not calibrated, so distances on it are unknown.
      </p>
    {/if}

    <button type="button" class="draw" aria-pressed={drawMode} onclick={toggleDrawMode}>
      {drawMode ? `Finish the zone (${drawing.length} corners)` : 'Draw a zone'}
    </button>
  </div>

  <p class="live" role="status" aria-live="polite">{announcement}</p>
</div>

<style>
  .wrap {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
  }

  .summary {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .canvas {
    width: 100%;
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
  }
  .canvas:focus-visible {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .canvas.placing {
    border-style: dashed;
    border-color: var(--moh-accent);
  }

  .under {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--moh-space-2);
  }

  .scale {
    display: inline-flex;
    align-items: center;
    gap: var(--moh-space-2);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink);
  }
  .bar {
    display: inline-block;
    height: 6px;
    border: 1px solid var(--moh-ink);
    border-top: none;
  }
  .bar-label {
    font-variant-numeric: tabular-nums;
  }

  .uncal {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .draw {
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-4);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: transparent;
    color: var(--moh-accent);
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-base);
    cursor: pointer;
  }
  .draw[aria-pressed='true'] {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
  }

  .live {
    margin: 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
    min-height: 1.4em;
  }

  /* Leaflet builds its markers outside this component's scope, so the pin and
     the zone need global rules. They still use the design system's tokens and no literals. */
  /* A pin sits on somebody's scan, and this app cannot know what colour that
     scan is. Measured at 375px, `--moh-accent` on a pale plan came out at
     5.72:1 in parchment and **2.10:1 in greenhouse** — under the 3:1 that
     WCAG 1.4.11 asks of a graphical object you have to be able to see.
     Re-tinting would only move the failure to a differently-coloured sheet.

     So the pin carries both a light band and a dark one, which is how a map
     marker has always survived arbitrary imagery: `--moh-surface-raised` and
     `--moh-ink` are opposite ends of whichever theme is on, so against any
     background at all one of the two rings clears 3:1. The dot is then read
     against its own inner ring rather than against the sheet. */
  :global(.moh-pin-dot) {
    display: block;
    width: 14px;
    height: 14px;
    margin: 5px;
    border-radius: 50%;
    background: var(--moh-accent);
    box-shadow:
      0 0 0 2px var(--moh-surface-raised),
      0 0 0 4px var(--moh-ink);
  }
  /* Selection is a *size*, not a colour. `--moh-parched` against
     `--moh-accent` measures 1.44:1 in parchment and 1.03:1 in greenhouse —
     the two are all but equiluminant in the dark theme, so a hue swap alone
     would mark the selected pin for nobody. The dot grows, both rings
     thicken, and the hue change is a garnish on top of a difference anyone
     can see. (The list row highlights at the same time, which is the other
     half of the answer.) */
  :global(.moh-pin-dot.is-selected) {
    width: 20px;
    height: 20px;
    margin: 2px;
    background: var(--moh-parched);
    box-shadow:
      0 0 0 3px var(--moh-surface-raised),
      0 0 0 6px var(--moh-ink);
  }
  :global(.moh-pin:focus-visible) {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }
  :global(.moh-zone) {
    stroke: var(--moh-accent);
    fill: var(--moh-accent);
  }
  :global(.moh-zone-draft) {
    stroke: var(--moh-parched);
  }
  /* The crosshair is over the same unknown sheet, and gets the same treatment:
     a dark dashed ring inside a light one, so it is visible on a white plan
     and on a dark aerial alike. */
  :global(.moh-crosshair-mark) {
    display: block;
    width: 24px;
    height: 24px;
    margin: 4px;
    border-radius: 50%;
    border: 3px dashed var(--moh-ink);
    background: transparent;
    box-shadow:
      0 0 0 2px var(--moh-surface-raised),
      inset 0 0 0 2px var(--moh-surface-raised);
  }
</style>
