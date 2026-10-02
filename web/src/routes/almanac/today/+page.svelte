<script lang="ts">
  /** This day, hour by hour.
   *
   *  Two charts rather than one: temperature is a shape and rain is a
   *  quantity, and a second y-axis is a way of making both harder to read on a
   *  phone held at arm's length in the sun.
   */
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import StaleNotice from '$ui/StaleNotice.svelte';
  import Caveats from '../../shared/Caveats.svelte';
  import Chart from '../Chart.svelte';
  import SiteMissing from '../SiteMissing.svelte';
  import {
    dayLabel,
    dayOf,
    formatPrecip,
    formatTemp,
    hourlyExtremes,
    hourlyRows,
    totalPrecip,
  } from '../forecast';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const points = $derived(data.forecast.value ?? []);
  const rows = $derived(hourlyRows(points));
  const extremes = $derived(hourlyExtremes(rows));
  const rain = $derived(totalPrecip(rows));
  const day = $derived(points.length ? dayLabel(dayOf(points[0])) : '');

  const times = $derived(rows.map((row) => row.at));
  const temperature = $derived([times, rows.map((row) => row.tempC)]);
  const precipitation = $derived([times, rows.map((row) => row.precipMm)]);

  const tempSeries = [{ plain: 'Temperature', colorToken: '--moh-parched' }];
  const rainSeries = [{ plain: 'Rain in the hour', colorToken: '--moh-sated', bars: true }];

  /** The hours worth printing in the table: every third one, plus any hour it
   *  rains. Twenty-four rows on a phone is a scroll, not a reading. */
  const tableRows = $derived(
    rows.filter((row, index) => index % 3 === 0 || (row.precipMm ?? 0) > 0),
  );
</script>

{#if !data.siteId}
  <SiteMissing reason={data.locationsError ?? undefined} />
{:else if data.forecast.error}
  <StaleNotice
    themed="The skies are closed to us"
    plain="Today's hourly forecast"
    asOf={null}
    reason={data.forecast.error}
  />
{:else if !rows.length}
  <EmptyState
    icon="sun"
    themed="The glass is empty"
    plain="No hourly forecast has arrived"
    body="The weather ingest has not stored an hourly forecast for this site yet."
  />
{:else}
  <div class="stack">
    <Caveats payload={points[0]} what="Today's forecast" />

    <Card themed="The day in brief" plain={day ? `Today — ${day}` : 'Today'} level={2}>
      <dl class="brief">
        <div>
          <dt>High</dt>
          <dd>{formatTemp(extremes.high)}</dd>
        </div>
        <div>
          <dt>Low</dt>
          <dd>{formatTemp(extremes.low)}</dd>
        </div>
        <div>
          <dt>Rain today</dt>
          <dd>{formatPrecip(rain)}</dd>
        </div>
      </dl>
    </Card>

    <Card themed="The hours" plain="Temperature through today" level={2}>
      <Chart
        showTitle={false}
        plain="Temperature by hour"
        themed="The warmth of the day"
        unit="°C"
        summary={`From ${formatTemp(extremes.low)} to ${formatTemp(extremes.high)} across the day.`}
        data={temperature}
        series={tempSeries}
      >
        {#snippet table()}
          <table>
            <caption class="visually-hidden">Temperature and rain, by hour</caption>
            <thead>
              <tr>
                <th scope="col">Hour</th>
                <th scope="col">Temperature</th>
                <th scope="col">Rain</th>
              </tr>
            </thead>
            <tbody>
              {#each tableRows as row (row.iso)}
                <tr>
                  <th scope="row">{row.label}</th>
                  <td>{formatTemp(row.tempC)}</td>
                  <td>{formatPrecip(row.precipMm)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/snippet}
      </Chart>
    </Card>

    <Card themed="What falls" plain="Rain by hour" level={2}>
      {#if rain > 0}
        <Chart
          showTitle={false}
          plain="Rain by hour"
          themed="What falls"
          unit="mm"
          summary={`${rain} mm expected across the day.`}
          data={precipitation}
          series={rainSeries}
        />
      {:else}
        <!-- A chart of twenty-four zeroes is a chart of nothing, drawn against
             whatever range the library invents for a flat line. The sentence
             says the same thing and says it in one glance. -->
        <p class="none">
          No rain is forecast today, so nothing waters itself. Anything due for watering is due from
          you.
        </p>
      {/if}
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
  .brief {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-6);
    margin: 0;
  }
  dt {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .none {
    margin: 0;
    color: var(--moh-ink-muted);
  }
  dd {
    margin: var(--moh-space-1) 0 0;
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-xl);
  }
</style>
