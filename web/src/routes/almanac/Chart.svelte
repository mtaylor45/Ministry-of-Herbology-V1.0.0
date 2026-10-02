<script lang="ts">
  /** A uPlot chart with the numbers underneath it.
   *
   *  The chart is a picture of data that is also present as text: the sentence
   *  above it says what it shows, and the table inside "the numbers" carries
   *  every value the line is drawn from. That is not a consolation prize for
   *  screen-reader users — it is the version that works on a phone in direct
   *  sun, which is where this app is read.
   *
   *  The canvas itself is hidden from assistive technology rather than given a
   *  hopeful `aria-label`: a 240-point temperature trace has no useful label,
   *  and the table beside it is the honest equivalent.
   *
   *  uPlot is loaded only in the browser, so this component server-renders to
   *  its text half and never asks Node for a canvas.
   */
  import type { Snippet } from 'svelte';
  // uPlot's own stylesheet sizes the canvas it creates. Without it the canvas
  // lays out at its device-pixel width — twice its drawn width on a phone —
  // and hangs off the side of the card.
  import 'uplot/dist/uPlot.min.css';
  import { axisFont, token, type ChartSeries } from './chart';

  let {
    plain,
    themed,
    summary,
    unit = '',
    data,
    series,
    height = 220,
    xIsTime = true,
    showTitle = true,
    table,
    tableLabel = 'The numbers',
  }: {
    /** Plain name of what is plotted. */
    plain: string;
    themed?: string;
    /** One sentence saying what the chart shows, always visible. */
    summary?: string;
    unit?: string;
    /** uPlot columns: `[xs, ...ys]`. */
    data: (number | null)[][];
    /** One entry per y column, in the same order. */
    series: ChartSeries[];
    height?: number;
    /** x is unix seconds. False plots a plain numeric axis. */
    xIsTime?: boolean;
    /** False where the card around the chart already names it. The name is
     *  still rendered for a screen reader — a figure without one is a figure
     *  that announces itself as nothing. */
    showTitle?: boolean;
    /** The same values as a table — the chart's text equivalent. */
    table?: Snippet;
    tableLabel?: string;
  } = $props();

  let host = $state<HTMLDivElement | null>(null);
  /** The chart could not be drawn. The numbers below still can be. */
  let failed = $state(false);

  const points = $derived(data[0]?.length ?? 0);

  $effect(() => {
    const element = host;
    // Tracked so the chart is rebuilt when either changes.
    const columns = data;
    const specs = series;
    if (!element || !columns.length) return;

    let plot: { destroy(): void; setSize(size: { width: number; height: number }): void } | null =
      null;
    let cancelled = false;
    let sizeWatch: ResizeObserver | null = null;
    let themeWatch: MutationObserver | null = null;

    void (async () => {
      try {
        const { default: UPlot } = await import('uplot');
        if (cancelled || !element.isConnected) return;

        /** The width to draw at. The plot's own box is measured, never the
         *  canvas inside it: a chart that reports its own width back to a
         *  container that sizes to its content grows by a few pixels on every
         *  observation until it is wider than the phone. */
        const widthOf = () =>
          Math.max(
            120,
            Math.round(element.clientWidth || element.parentElement?.clientWidth || 320),
          );

        const draw = () => {
          plot?.destroy();
          const rootPx =
            Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
          const ink = token(element, '--moh-ink-muted');
          const grid = token(element, '--moh-border');
          const font = axisFont(element, rootPx);

          plot = new UPlot(
            {
              width: widthOf(),
              height,
              padding: [null, null, null, null],
              legend: { show: false },
              cursor: { y: false, points: { size: 6 } },
              scales: { x: { time: xIsTime } },
              axes: [
                { stroke: ink, font, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid } },
                {
                  stroke: ink,
                  font,
                  grid: { stroke: grid, width: 1 },
                  ticks: { stroke: grid },
                  size: 44,
                },
              ],
              series: [
                { label: 'When' },
                ...specs.map((spec) => {
                  const stroke = token(element, spec.colorToken);
                  return {
                    label: spec.plain,
                    stroke,
                    width: 2,
                    dash: spec.dash ? [6, 4] : undefined,
                    // Bars are read as quantity, so they are filled; a line is
                    // read as a trend and is not.
                    fill: spec.fill || spec.bars ? stroke : undefined,
                    // `spanGaps: false` is the default and is the point: a day
                    // with no reading leaves a hole rather than a straight line
                    // drawn across the outage.
                    //
                    // A bar already marks where its value is; a point on top of
                    // one turns a column of rain into a lollipop.
                    points: { show: !spec.bars && points <= 24 },
                    paths: spec.bars ? UPlot.paths.bars?.({ size: [0.8, 24] }) : undefined,
                  };
                }),
              ],
            } as never,
            columns as never,
            element,
          ) as unknown as typeof plot;
        };

        draw();

        let drawnAt = widthOf();
        sizeWatch = new ResizeObserver(() => {
          const width = widthOf();
          if (width === drawnAt) return;
          drawnAt = width;
          plot?.setSize({ width, height });
        });
        sizeWatch.observe(element);

        // The tokens change value when the theme does, and a canvas cannot
        // inherit them — so it is redrawn.
        themeWatch = new MutationObserver(draw);
        themeWatch.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['data-theme'],
        });
      } catch {
        failed = true;
      }
    })();

    return () => {
      cancelled = true;
      sizeWatch?.disconnect();
      themeWatch?.disconnect();
      plot?.destroy();
    };
  });
</script>

<figure class="chart">
  <figcaption>
    <span class="name" class:visually-hidden={!showTitle}>
      {#if themed}<span class="themed">{themed}</span>{/if}
      <span class="plain">{plain}{unit ? ` (${unit})` : ''}</span>
    </span>
    {#if summary}<span class="summary">{summary}</span>{/if}
  </figcaption>

  <ul class="legend">
    {#each series as spec (spec.plain)}
      <li>
        <span
          class="key"
          class:dashed={spec.dash}
          class:bar={spec.bars}
          style:color={`var(${spec.colorToken})`}
          aria-hidden="true"
        ></span>
        {spec.plain}
      </li>
    {/each}
  </ul>

  {#if failed}
    <p class="failed">The chart could not be drawn on this device. The numbers are below.</p>
  {:else}
    <div class="plot" bind:this={host} style:min-height={`${height}px`} aria-hidden="true"></div>
  {/if}

  {#if table}
    <details class="numbers">
      <summary>{tableLabel}</summary>
      {@render table()}
    </details>
  {/if}
</figure>

<style>
  .chart {
    margin: 0;
  }
  figcaption {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
    margin-bottom: var(--moh-space-2);
  }
  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
  }
  .plain {
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .summary {
    font-size: var(--moh-text-sm);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-3);
    margin: 0 0 var(--moh-space-2);
    padding: 0;
    list-style: none;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
  }
  .key {
    width: var(--moh-space-6);
    border-top: 2px solid currentColor;
  }
  .key.dashed {
    border-top-style: dashed;
  }
  .key.bar {
    height: var(--moh-space-3);
    width: var(--moh-space-3);
    border: none;
    background: currentColor;
  }
  .plot {
    width: 100%;
    min-width: 0;
    /* The chart is drawn to the width it was measured at. If it ever disagrees,
       the page must not start scrolling sideways in the reader's hand. */
    overflow: hidden;
  }
  .plot :global(.uplot) {
    max-width: 100%;
  }
  .failed {
    margin: 0;
    padding: var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }
  .numbers {
    margin-top: var(--moh-space-3);
    font-size: var(--moh-text-sm);
  }
  .numbers summary {
    min-height: var(--moh-tap);
    display: flex;
    align-items: center;
    cursor: pointer;
    color: var(--moh-accent);
  }
  .numbers :global(table) {
    width: 100%;
    border-collapse: collapse;
  }
  .numbers :global(th),
  .numbers :global(td) {
    padding: var(--moh-space-2);
    border-bottom: 1px solid var(--moh-border);
    text-align: start;
  }
  .numbers :global(th) {
    font-family: var(--moh-font-body);
    font-weight: 600;
  }
</style>
