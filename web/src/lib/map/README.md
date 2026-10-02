# The Grounds — the maps module

Owned by the maps module. Floor plans and property surveys on Leaflet, calibration, specimen
pins, and the zone overlay. The API half is `api/grounds/`.

```svelte
<script>
  import { Grounds } from '$map';
</script>

<Grounds {layers} {pins} {zones} />
```

`Grounds` is the whole surface, so the app's screens's `/grounds` route can be one
element and the app's screens' releases is about the Specimen cross-links rather than about
rebuilding this. The parts (`GroundsMap`, `PinList`, `CalibrationPanel`,
`LayerUpload`) are exported for a screen that wants one of them.

## One component, two map kinds

a floor plan is a flat drawing with a `scale_mm_per_px`, a survey is
a raster georeferenced by at least two pixel↔world points. Both draw on
`CRS.Simple` over an image overlay and both keep **pins in layer pixels**, so
recalibrating re-places every pin correctly and a plan needs no fiction about
where on Earth it sits. The georeferencing shows up in the scale bar and the
readouts, not in a second map.

## Accessibility: the list is the map

A pin reachable only by pointing is unreachable by keyboard and invisible to a
screen reader. So:

- **`PinList` is the equivalent, not a summary.** It and the markers render
  from one array — `pinRows()` — so a marker cannot acquire behaviour the list
  lacks. Every pin is a real `<a href="/specimen/{id}/register">`, which is the
  releases's exit criterion reached without a pointer.
- **It is shown, not visually hidden.** A sighted keyboard user needs it too,
  and a hidden list is one refactor away from being a hidden _stale_ list.
- **Position is described in words.** "upper left of Ground floor, about 4 m in
  from the left edge" — never "at 412, 388", which is a fact about a raster and
  not a place. Uncalibrated, it says so instead of inventing a distance.
- **Placing a pin is a mode, not a drag.** Pick a plant, a crosshair appears,
  arrow keys move it (Shift for a finer step), Enter commits, Escape leaves it.
  The arithmetic is in `placement.ts` and tested without a browser.
- **A live region narrates the crosshair** by quadrant and by edge, because
  coordinates read aloud are noise.
- **The map container is `role="application"` and focusable.** That is what
  lets arrow keys reach the component at all. It is a heavy hammer, which is
  the other reason the list stays visible: the list works without it.

Status is never colour alone: a selected pin gets a ring as well as a hue, a
selected row gets a border as well as a background, and "calibrated" is a
sentence before it is a rule colour.

## Escalations — not worked around

**1. A zone can be drawn and cannot be saved.** `Location` carries
`boundary_px` and `map_layer_id`, so zones already drawn can be read and
rendered. But the body of `PATCH /locations/{id}` is `LocationCreate`, which
declares neither field — so there is no contract-legal way to persist a
boundary. `GroundsMap` therefore draws, and emits `onzonedrawn`, and says
plainly that it cannot save. **For A: `LocationCreate` (or a `LocationUpdate`)
needs `boundary_px` and `map_layer_id`.** Additive, and it belongs to the inventory API's
endpoint rather than to `/grounds`.

**2. `GET /grounds/layers/{id}/image` is served and is not in the contract.**
See `api/grounds/README.md`.

**3. Leaflet ships no types** and `web/package.json` is not the maps module's to change, so
`leaflet.d.ts` declares the module `any` at the boundary. Delete it the day
`@types/leaflet` is a dependency.

## Files

| File                      | What it is                                                      |
| ------------------------- | --------------------------------------------------------------- |
| `Grounds.svelte`          | The assembled surface; owns the state the map and list share    |
| `GroundsMap.svelte`       | The Leaflet wrapper: overlay, pins, zones, crosshair, scale bar |
| `PinList.svelte`          | The keyboard and screen-reader equivalent of the pins           |
| `CalibrationPanel.svelte` | Scale for a plan, control points for a survey                   |
| `LayerUpload.svelte`      | The multipart form, and the refusals in plain words             |
| `client.ts`               | `/grounds` calls; keeps the server's `detail` on every failure  |
| `projection.ts`           | px↔world, scale bar, distances                                  |
| `pins.ts`                 | The rows the map and the list are both drawn from               |
| `placement.ts`            | Keyboard placement arithmetic                                   |
| `types.ts`                | The contract's shapes                                           |

Leaflet is imported inside `onMount`: it touches `window` at module scope, and
the list has to exist in the server render or it is not an equivalent.
