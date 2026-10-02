<script lang="ts">
  /** What the weather has actually done — and, where anything measures it, what
   *  it has been like indoors at the same time.
   *
   *  The comparison is the reason this view exists: a study that runs warm and
   *  dry is why the same species is watered on a different round there than in
   *  the bed outside. Which is exactly why the indoor line is checked before it
   *  is drawn. Nothing in this house measures indoors yet, and a
   *  second line traced from the garden's own numbers would invent the very
   *  difference the reader came to look at.
   */
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import SelectField from '$ui/SelectField.svelte';
  import StaleNotice from '$ui/StaleNotice.svelte';
  import Caveats from '../../shared/Caveats.svelte';
  import Chart from '../Chart.svelte';
  import SiteMissing from '../SiteMissing.svelte';
  import {
    METRICS,
    WINDOWS,
    align,
    bucketLabel,
    columns,
    coverageSentence,
    freezingSentence,
    hasAnyValue,
    hasRange,
    indoorGap,
    indoorIsReal,
    metricsFor,
    rollupSentence,
    seriesFor,
    summary,
  } from '../history';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const outdoor = $derived(data.outdoor.value);
  const indoorSeries = $derived(data.indoor?.value ?? null);
  const showIndoor = $derived(indoorIsReal(indoorSeries));
  const gap = $derived(data.indoor ? indoorGap(indoorSeries, data.metric) : null);

  const rows = $derived(align(outdoor, showIndoor ? indoorSeries : null));
  /** The daily extremes where the rollup carries them, the daily mean where it
   *  does not. On a month of weather the mean is the line that hides the frost;
   *  see `hasRange` in `history.ts`. */
  const shape = $derived({ range: hasRange(rows), indoor: showIndoor });
  const chartData = $derived(columns(rows, shape));
  const unit = $derived(METRICS[data.metric].unit);
  const series = $derived(seriesFor(shape, data.room?.name ?? null));

  const rollup = $derived(rollupSentence(outdoor));
  const coverage = $derived(coverageSentence(rows, data.window));
  const frost = $derived(freezingSentence(rows, data.metric));

  const metricOptions = $derived(
    metricsFor('site').map((metric) => ({
      value: metric,
      plain: METRICS[metric].plain,
      themed: METRICS[metric].themed,
    })),
  );

  const windowOptions = Object.entries(WINDOWS).map(([value, label]) => ({
    value,
    plain: label.plain,
    themed: label.themed,
  }));

  const roomOptions = $derived(data.indoors.map((room) => ({ value: room.id, plain: room.name })));
</script>

<div class="stack">
  <Card themed="What to consult" plain="Choose the record to show" level={2}>
    <!-- A plain GET form: the three views are linkable, the choice survives a
         reload, and none of it needs JavaScript to work. -->
    <form class="controls" method="GET" action="/almanac/history">
      <SelectField
        name="metric"
        value={data.metric}
        options={metricOptions}
        themed="The measure"
        plain="What to show"
      />
      <SelectField
        name="window"
        value={data.window}
        options={windowOptions}
        themed="How far back"
        plain="Period"
      />
      {#if roomOptions.length}
        <SelectField
          name="location"
          value={data.room?.id ?? ''}
          options={roomOptions}
          themed="Which room"
          plain="Indoor location to compare"
        />
      {/if}
      <div class="go">
        <!-- The themed half is back: `Label` now paints the plain half through
             `--moh-plain-ink`, which a filled control re-declares as its own
             ink. Measured on this button at 10.91:1 on
             parchment and 6.68:1 on greenhouse, both halves. -->
        <Button type="submit" themed="Consult the record" plain="Show this record" />
      </div>
    </form>
  </Card>

  {#if !data.siteId}
    <SiteMissing reason={data.locationsError ?? undefined} />
  {:else if data.outdoor.error}
    <StaleNotice
      themed="The record is closed to us"
      plain="The conditions history"
      asOf={null}
      reason={data.outdoor.error}
    />
  {:else}
    <Card
      themed={METRICS[data.metric].themed}
      plain={`${METRICS[data.metric].plain} — ${WINDOWS[data.window].plain}`}
      level={2}
    >
      {#if !hasAnyValue(outdoor)}
        <p class="empty">
          Nothing has been recorded for {METRICS[data.metric].plain.toLowerCase()} over this period. The
          series came back with the right shape and no values in it, which is the honest answer — no figure
          has been estimated to fill it.
        </p>
      {:else}
        {#if coverage}
          <p class="coverage">{coverage}</p>
        {/if}

        <Chart
          showTitle={false}
          plain={`${METRICS[data.metric].plain}${showIndoor ? ', indoors and out' : ', outdoors'}`}
          themed={METRICS[data.metric].themed}
          {unit}
          summary={summary(rows, data.metric, shape)}
          data={chartData}
          {series}
        >
          {#snippet table()}
            <table>
              <caption class="visually-hidden">
                {METRICS[data.metric].plain} by day, {WINDOWS[data.window].plain.toLowerCase()}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  {#if shape.range}
                    <th scope="col">Low</th>
                    <th scope="col">Mean</th>
                    <th scope="col">High</th>
                  {:else}
                    <th scope="col">Outdoors</th>
                  {/if}
                  {#if showIndoor}<th scope="col">Indoors</th>{/if}
                </tr>
              </thead>
              <tbody>
                {#each rows as row (row.at)}
                  <tr>
                    <th scope="row">{bucketLabel(row.at)}</th>
                    {#if shape.range}
                      <td>{row.low === null ? 'not recorded' : `${row.low} ${unit}`}</td>
                      <td>{row.outdoor === null ? 'not recorded' : `${row.outdoor} ${unit}`}</td>
                      <td>{row.high === null ? 'not recorded' : `${row.high} ${unit}`}</td>
                    {:else}
                      <td>{row.outdoor === null ? 'not recorded' : `${row.outdoor} ${unit}`}</td>
                    {/if}
                    {#if showIndoor}
                      <td>{row.indoor === null ? 'not recorded' : `${row.indoor} ${unit}`}</td>
                    {/if}
                  </tr>
                {/each}
              </tbody>
            </table>
          {/snippet}
        </Chart>

        {#if frost}
          <p class="frost">{frost}</p>
        {/if}
        {#if rollup}
          <p class="rollup">{rollup}</p>
        {/if}
      {/if}

      {#if gap}
        <div class="gap">
          <h3>Indoors, there is nothing to compare</h3>
          <p>{gap}</p>
        </div>
      {/if}
    </Card>

    <Caveats payload={outdoor} what="This record" />
  {/if}
</div>

<style>
  .stack {
    display: grid;
    /* `minmax(0, 1fr)`, not `1fr`: a grid item's automatic minimum is its
       content, and a chart canvas is content that would rather be wider. */
    grid-template-columns: minmax(0, 1fr);
    gap: var(--moh-space-6);
  }
  .controls {
    display: grid;
    gap: var(--moh-space-4);
  }
  @media (min-width: 640px) {
    .controls {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: end;
    }
  }
  .go {
    display: flex;
  }
  .empty,
  .rollup,
  .gap p {
    margin: 0;
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .rollup {
    margin-top: var(--moh-space-3);
  }
  .coverage,
  .frost {
    margin: 0 0 var(--moh-space-3);
    padding: var(--moh-space-3);
    border-inline-start: 4px solid var(--moh-frost);
    background: var(--moh-surface-sunken);
    border-radius: var(--moh-radius);
    font-size: var(--moh-text-sm);
  }
  .frost {
    margin: var(--moh-space-3) 0 0;
  }
  .gap {
    margin-top: var(--moh-space-4);
    padding: var(--moh-space-3);
    border: 1px dashed var(--moh-border);
    border-radius: var(--moh-radius);
  }
  .gap h3 {
    margin: 0 0 var(--moh-space-2);
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-sm);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--moh-ink-muted);
  }
</style>
