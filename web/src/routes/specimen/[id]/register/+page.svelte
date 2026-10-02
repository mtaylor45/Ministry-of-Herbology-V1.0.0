<script lang="ts">
  /** Register Entry — where the plant stands, where it came from, what it is
   *  potted in, and what has been written down about it since. */
  import { Card, EmptyState, ListRow, StaleNotice } from '$ui';
  import type { PageData } from './$types';
  import FactList from '../FactList.svelte';
  import SeeAlso from '../SeeAlso.svelte';
  import WhereOnMap from '../WhereOnMap.svelte';
  import type { Fact } from '../facts';
  import { LOCATION_KIND, LOG_KINDS, SUN_EXPOSURE, formatDate } from '../labels';
  import { place as resolvePlace } from '../mapPlace';

  let { data }: { data: PageData } = $props();

  const specimen = $derived(data.specimen);

  const place = $derived<Fact[]>(
    specimen.location
      ? [
          { plain: 'Location', themed: 'Where it stands', value: specimen.location.name },
          {
            plain: 'Kind of place',
            value: LOCATION_KIND[specimen.location.kind] ?? specimen.location.kind,
          },
          {
            plain: 'Indoors or out',
            value: specimen.is_outdoor ? 'Outdoors' : 'Indoors',
            note: specimen.is_outdoor
              ? specimen.location.is_covered
                ? 'Covered, so rain does not reach it — the water balance treats it as sheltered.'
                : 'Open to the sky, so rainfall counts against its watering.'
              : 'Watering is scheduled by interval; rain and frost do not apply.',
          },
          {
            plain: 'Sun',
            themed: 'Light it is given',
            value: SUN_EXPOSURE[specimen.location.sun_exposure ?? 'unknown'] ?? 'Not recorded',
          },
          {
            plain: 'Others in this place',
            value:
              specimen.location.specimen_count > 1
                ? `${specimen.location.specimen_count - 1} other plant${specimen.location.specimen_count === 2 ? '' : 's'}`
                : 'This one alone',
          },
        ]
      : [
          {
            plain: 'Location',
            themed: 'Where it stands',
            value: 'Not recorded',
            note: 'Without a location there is no weather for this plant, so no rain, frost or water balance applies to it.',
          },
        ],
  );

  const provenance = $derived<Fact[]>([
    { plain: 'Acquired', themed: 'Came into keeping', value: formatDate(specimen.acquired_on) },
    { plain: 'How it came here', value: specimen.provenance ?? 'Not recorded' },
    { plain: 'Added to the Register', value: formatDate(specimen.created_at) },
    {
      plain: 'Count',
      value: specimen.is_group ? `A group of ${specimen.count}` : 'A single plant',
      note: specimen.is_group ? 'Tasks and care cover the whole group as one entry.' : undefined,
    },
    { plain: 'Nickname', themed: 'What it is called', value: specimen.nickname ?? 'None given' },
  ]);

  const container = $derived<Fact[]>([
    {
      plain: 'Planting',
      themed: 'How it is housed',
      value: specimen.in_container ? 'In a container' : 'In the ground',
      note: specimen.in_container
        ? 'A container holds less water than open ground and reaches its watering threshold sooner.'
        : 'Open ground holds more water, so the deficit builds more slowly.',
    },
    {
      plain: 'Container size',
      value:
        specimen.container_litres != null ? `${specimen.container_litres} litres` : 'Not recorded',
    },
    { plain: 'Soil', themed: 'What it is bedded in', value: specimen.soil_note ?? 'Not recorded' },
  ]);

  const photos = $derived(data.photos.value ?? []);
  const log = $derived(data.log.value ?? []);

  // A failed Grounds read is passed through as `null` rather than as an empty
  // list, because "no pin" and "could not be asked" are different answers and
  // only one of them is this plant's fault.
  const onTheMap = $derived(
    resolvePlace(
      specimen,
      data.layers.value,
      data.pins.value,
      data.layers.error ?? data.pins.error ?? null,
    ),
  );
</script>

<div class="stack">
  <Card themed="Where it stands" plain="Location" level={2}>
    <FactList facts={place} />
  </Card>

  <!-- The map side of the Register entry. Its own panel rather than a row
       inside "Where it stands", because what it has to say is a sentence and a
       caveat, not a one-line fact — and on an uncalibrated sheet the caveat is
       the half that matters. -->
  <WhereOnMap place={onTheMap} />

  <Card themed="Provenance" plain="Where it came from" level={2}>
    <FactList facts={provenance} />
  </Card>

  <Card themed="Pot and soil" plain="Container and soil" level={2}>
    <FactList facts={container} />
  </Card>

  <Card themed="Likenesses" plain="Photographs" level={2}>
    {#if data.photos.error}
      <StaleNotice plain="The photograph list" asOf={null} reason={data.photos.error} />
    {:else if photos.length}
      <ul class="plates">
        {#each photos as photo (photo.id)}
          <li>
            <img
              src={photo.thumb_url ?? photo.url}
              alt={photo.caption ?? `Photograph of ${specimen.display_name}`}
              loading="lazy"
            />
            <p class="caption">
              {photo.caption ?? 'No caption'}
              <span class="when">{formatDate(photo.taken_at)}</span>
            </p>
          </li>
        {/each}
      </ul>
    {:else}
      <EmptyState
        icon="camera"
        themed="No likenesses taken"
        plain="No photographs yet"
        body="Photographs are uploaded from the growth log. The upload endpoint is the inventory API's and lands this release; until then this stays empty rather than showing a placeholder."
      />
    {/if}
  </Card>

  <Card themed="The growth log" plain="Growth, pests and repotting" level={2}>
    {#if data.log.error}
      <StaleNotice plain="The growth log" asOf={null} reason={data.log.error} />
    {:else if log.length}
      <ul class="log">
        {#each log as entry (entry.id)}
          {@const kind = LOG_KINDS[entry.kind] ?? { themed: entry.kind, plain: entry.kind }}
          <li>
            <ListRow
              themed={kind.themed}
              plain={kind.plain}
              meta={`${formatDate(entry.occurred_at)}${entry.body ? ` — ${entry.body}` : ''}`}
              icon="quill"
            />
          </li>
        {/each}
      </ul>
    {:else}
      <EmptyState
        icon="quill"
        themed="Nothing yet set down"
        plain="Nothing written in the log yet"
        body="Growth notes, pests, prunings and repottings are recorded here. Writing an entry needs the inventory API's POST endpoint, which is not built yet."
      />
    {/if}
  </Card>

  <SeeAlso current="register" specimenId={specimen.id} />
</div>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }
  .log {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  .plates {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
    gap: var(--moh-space-3);
  }
  .plates img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    border-radius: var(--moh-radius);
    border: 1px solid var(--moh-border);
  }
  .caption {
    margin: var(--moh-space-1) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .when {
    display: block;
  }
</style>
