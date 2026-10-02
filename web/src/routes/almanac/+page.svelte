<script lang="ts">
  /** The ten days ahead: highs, lows, rain, and the cold nights called out.
   *
   *  The strip is the primary reading — one thumb, one column, no horizontal
   *  scrolling — and the chart beneath it is for the shape of the week. Both
   *  are drawn from the same rows, so they cannot disagree.
   */
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import StaleNotice from '$ui/StaleNotice.svelte';
  import Caveats from '../shared/Caveats.svelte';
  import Chart from './Chart.svelte';
  import DayRow from './DayRow.svelte';
  import SiteMissing from './SiteMissing.svelte';
  import {
    dailyRows,
    daySentence,
    formatPrecip,
    formatTemp,
    freezingPct,
    frostNights,
    temperatureDomain,
    totalPrecip,
  } from './forecast';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const points = $derived(data.forecast.value ?? []);
  const rows = $derived(dailyRows(points));
  const domain = $derived(temperatureDomain(rows));
  const freezing = $derived(freezingPct(domain));
  const cold = $derived(frostNights(rows));
  const rain = $derived(totalPrecip(rows));

  /** uPlot columns: the day at noon so a bar sits over its own date, then the
   *  two lines. */
  const columns = $derived([
    rows.map((row) => Date.parse(`${row.day}T12:00:00Z`) / 1000),
    rows.map((row) => row.high),
    rows.map((row) => row.low),
  ]);

  const series = [
    { plain: 'Daily high', colorToken: '--moh-parched' },
    { plain: 'Daily low', colorToken: '--moh-frost', dash: true },
  ];
</script>

{#if !data.siteId}
  <SiteMissing reason={data.locationsError ?? undefined} />
{:else if data.forecast.error}
  <StaleNotice
    themed="The skies are closed to us"
    plain="The ten-day forecast"
    asOf={null}
    reason={data.forecast.error}
  />
{:else if !rows.length}
  <EmptyState
    icon="sun"
    themed="The glass is empty"
    plain="No forecast has arrived"
    body="The weather ingest has not stored a forecast for this site yet. Nothing has been guessed in the meantime."
  />
{:else}
  <div class="stack">
    <Caveats payload={points[0]} what="This forecast" />

    {#if cold.length}
      <Card themed="Nights to watch" plain="Cold nights in the next ten" level={2} tone="accent">
        <ul class="nights">
          {#each cold as night (night.day)}
            <li>{daySentence(night)}</li>
          {/each}
        </ul>
        <p class="seam">
          These are the nights, not the plants. Which specimens need carrying in or covering depends
          on each one's own minimum temperature and whether it stands in a pot or in the ground —
          that is the frost guard's answer, and it is not read here yet. Under the design the frost
          endpoint gains an envelope so the plants it <em>cannot</em> judge are reported beside the ones
          it can; when that lands, both belong on this card.
        </p>
      </Card>
    {/if}

    <Card themed="The ten days" plain="Daily highs, lows and rain" level={2}>
      <p class="lede">
        {rows.length} days ahead. {rain > 0
          ? `${rain} mm of rain expected in total.`
          : 'No rain expected.'}
      </p>
      <div class="strip">
        {#each rows as row (row.day)}
          <DayRow {row} {domain} freezingAt={freezing} />
        {/each}
      </div>
    </Card>

    <Card themed="The shape of the week" plain="High and low temperature" level={2}>
      <Chart
        showTitle={false}
        plain="Daily high and low"
        themed="Warmth ahead"
        unit="°C"
        summary={`Highs ${formatTemp(Math.max(...rows.map((r) => r.high ?? -Infinity)))} at most, lows ${formatTemp(Math.min(...rows.map((r) => r.low ?? Infinity)))} at least.`}
        data={columns}
        {series}
      >
        {#snippet table()}
          <table>
            <caption class="visually-hidden">Daily high and low temperature, and rain</caption>
            <thead>
              <tr>
                <th scope="col">Day</th>
                <th scope="col">High</th>
                <th scope="col">Low</th>
                <th scope="col">Rain</th>
              </tr>
            </thead>
            <tbody>
              {#each rows as row (row.day)}
                <tr>
                  <th scope="row">{row.label}</th>
                  <td>{formatTemp(row.high)}</td>
                  <td>{formatTemp(row.low)}</td>
                  <td>{formatPrecip(row.precipMm)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/snippet}
      </Chart>
    </Card>
  </div>
{/if}

<style>
  .stack {
    display: grid;
    /* `minmax(0, 1fr)`, not `1fr`: a grid item's automatic minimum is its
       content, and a chart canvas is content that would rather be wider. */
    grid-template-columns: minmax(0, 1fr);
    gap: var(--moh-space-6);
  }
  .lede {
    margin: 0 0 var(--moh-space-2);
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .strip > :global(div:last-child) {
    border-bottom: none;
  }
  .nights {
    margin: 0;
    padding-inline-start: var(--moh-space-4);
    display: grid;
    gap: var(--moh-space-2);
  }
  .seam {
    margin: var(--moh-space-3) 0 0;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
</style>
