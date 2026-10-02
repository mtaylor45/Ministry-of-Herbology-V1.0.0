<script lang="ts">
  /** Compendium — what is known about the species, and who said so.
   *
   *  The no-invented-plant-facts rule does the editing here: nothing on this page is written by the app.
   *  The summary is prose a source supplied, the taxonomy and native range come
   *  from POWO and GBIF, and the toxicity flags carry their citations. Where a
   *  section has no sourced content it says so instead of being filled in.
   */
  import { Card, EmptyState, ListRow, StaleNotice, StatusPill } from '$ui';
  import type { PageData } from './$types';
  import FactList from '../FactList.svelte';
  import SeeAlso from '../SeeAlso.svelte';
  import type { Fact } from '../facts';
  import { confidenceStatus, formatValue, sourceKind } from '../care';
  import { formatDate } from '../labels';

  let { data }: { data: PageData } = $props();

  const specimen = $derived(data.specimen);
  const species = $derived(data.species.value);
  const careValues = $derived(data.careValues.value ?? []);

  const MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];

  const taxonomy = $derived<Fact[]>(
    species
      ? [
          { plain: 'Accepted name', themed: 'Name of record', value: species.accepted_name },
          { plain: 'Cultivar', value: specimen.cultivar ?? 'None recorded' },
          { plain: 'Family', value: species.family ?? 'Not recorded' },
          { plain: 'Genus', value: species.genus ?? 'Not recorded' },
          {
            plain: 'Also called',
            themed: 'Common names',
            value: species.common_names?.length
              ? species.common_names.join(', ')
              : 'No common name recorded',
          },
          {
            plain: 'Hardiness zones',
            value:
              species.usda_zone_min || species.usda_zone_max
                ? `USDA ${species.usda_zone_min ?? '?'} to ${species.usda_zone_max ?? '?'}`
                : 'Not recorded',
          },
          {
            plain: 'Dormant months',
            themed: 'When it slumbers',
            value: species.dormancy_months?.length
              ? species.dormancy_months.map((m) => MONTHS[m - 1] ?? String(m)).join(', ')
              : 'No dormancy recorded',
            note: species.dormancy_months?.length
              ? 'Watering and feeding are eased back over these months.'
              : undefined,
          },
        ]
      : [],
  );

  const toxicity = $derived(careValues.filter((v) => v.field.startsWith('toxic_to_')));
</script>

<div class="stack">
  {#if data.species.error}
    <StaleNotice plain="The species record" asOf={null} reason={data.species.error} />
  {:else if !species}
    <EmptyState
      icon="search"
      themed="No entry in the Compendium"
      plain="This plant has not been matched to a species"
      body="Until it is identified there is nothing to look up, and nothing has been guessed in the meantime. Identify it from the Register entry."
    />
  {:else}
    <Card themed="In brief" plain="Summary" level={2}>
      {#if species.summary}
        <p class="summary">{species.summary}</p>
        <p class="aside">
          Drawn from the sources listed at the foot of this page. Nothing on this facet is written
          by the app itself.
        </p>
      {:else}
        <EmptyState
          icon="book"
          themed="No account of it yet"
          plain="No summary recorded"
          body="No source consulted supplied a description of this species. Rather than write one, the app leaves it blank."
        />
      {/if}
    </Card>

    <Card themed="Its proper name" plain="Taxonomy" level={2}>
      <FactList facts={taxonomy} />
    </Card>

    <Card themed="Where it grows wild" plain="Native range" level={2}>
      {#if species.native_range?.length}
        <p>{species.native_range.join(' · ')}</p>
      {:else}
        <p>No native range recorded for this species.</p>
      {/if}
    </Card>

    <Card
      themed="Cautions"
      plain="Toxicity to children and pets"
      level={2}
      tone={species.toxic_to_pets || species.toxic_to_children ? 'danger' : 'plain'}
    >
      {#if toxicity.length}
        <ul class="tox">
          {#each toxicity as value (value.field)}
            <li>
              <p class="tox-line">
                <span class="tox-name">
                  {value.field === 'toxic_to_pets' ? 'Toxic to pets' : 'Toxic to children'}:
                  <strong>{formatValue(value.value, value.field, value.unit)}</strong>
                </span>
                <StatusPill status={confidenceStatus(value.confidence, value.is_user_override)} />
              </p>
              <p class="aside">
                {#if value.source}
                  Source: {sourceKind(value.source.kind)} —
                  {#if value.source.url}
                    <a href={value.source.url} rel="noreferrer noopener" target="_blank"
                      >{value.source.title}</a
                    >
                  {:else}{value.source.title}{/if}
                {:else}
                  No source. Treat this as unknown, not as a clean bill of health.
                {/if}
              </p>
            </li>
          {/each}
        </ul>
      {:else}
        <p>
          No toxicity finding either way. That is not the same as safe — no source consulted said
          anything about it.
        </p>
      {/if}
      {#if species.toxicity_note}
        <p class="tox-note">{species.toxicity_note}</p>
      {/if}
      <p class="aside">
        Correct any of these on the Tending facet; your correction wins over every source.
      </p>
    </Card>

    <Card themed="Lore and uses" plain="History and uses" level={2}>
      <EmptyState
        icon="book"
        themed="The Compendium is silent here"
        plain="No lore or uses recorded"
        body="The contract has no field for lore or traditional uses, so there is nowhere for a cited account to be stored. Rather than write one, this section stays empty — raised with the maintainers."
      />
    </Card>

    <Card themed="Whence this came" plain="Sources" level={2}>
      {#if species.sources?.length}
        <ul class="sources">
          {#each species.sources as source (source.id)}
            <li>
              <ListRow
                themed={sourceKind(source.kind)}
                plain={source.title}
                meta={`${source.license ?? 'Licence not recorded'} · read ${formatDate(source.retrieved_at, 'at an unrecorded time')}`}
                href={source.url ?? undefined}
                icon="book"
              />
            </li>
          {/each}
        </ul>
      {:else}
        <p>No sources recorded. Everything above should be read as unverified.</p>
      {/if}
    </Card>
  {/if}

  <SeeAlso current="compendium" specimenId={specimen.id} />
</div>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }
  .summary {
    margin: 0;
    font-size: var(--moh-text-lg);
  }
  .aside,
  .tox-note {
    margin: var(--moh-space-3) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .tox,
  .sources {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-3);
  }
  .tox-line {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--moh-space-2);
  }
  .tox-name {
    font-size: var(--moh-text-base);
  }
</style>
