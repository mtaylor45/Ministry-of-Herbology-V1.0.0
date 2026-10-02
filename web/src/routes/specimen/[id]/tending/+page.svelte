<script lang="ts">
  /** Tending — the care profile with its sources, the schedule it produces,
   *  the water balance behind it and the frost guard watching over it.
   *
   *  the design is why this facet is shaped the way it is: with no soil probe in
   *  the house, the water balance is the sole authority on outdoor watering,
   *  and the confidence in `water_k_c` is what the reader is really being asked
   *  to trust. It sits next to the recommendation, not behind a tap.
   */
  import { invalidate } from '$app/navigation';
  import { Card, EmptyState, ListRow, StaleNotice, StatusPill, STATUS } from '$ui';
  import type { PageData } from './$types';
  import CareValueList from '../CareValueList.svelte';
  import FactList from '../FactList.svelte';
  import SeeAlso from '../SeeAlso.svelte';
  import type { Fact } from '../facts';
  import { confidenceStatus, sourceKind } from '../care';
  import { CARE_STRATEGIES, TASK_TYPES, formatDate } from '../labels';

  let { data }: { data: PageData } = $props();

  const specimen = $derived(data.specimen);
  const careValues = $derived(data.careValues.value ?? []);
  const water = $derived(data.water.value);
  const tasks = $derived(data.tasks.value ?? []);
  const rules = $derived(data.rules.value ?? []);

  /** The coefficient the outdoor model multiplies evaporation by, and how much
   *  anybody actually knows about it. */
  const kC = $derived(careValues.find((v) => v.field === 'water_k_c') ?? null);

  const frostAlerts = $derived(
    (data.frost.value?.alerts ?? []).filter(
      (a) => a.specimen.id === specimen.id && a.state === 'open',
    ),
  );

  const waterFacts = $derived<Fact[]>(
    water
      ? [
          {
            plain: 'Soil water deficit',
            themed: 'Thirst accrued',
            value: `${water.deficit_mm} mm of ${water.capacity_mm} mm the soil can hold`,
          },
          {
            plain: 'Waters when the deficit reaches',
            value: `${water.threshold_mm} mm`,
            note: water.is_due
              ? 'The deficit is at or past the threshold, so a watering is due.'
              : `${Math.round((water.threshold_mm - water.deficit_mm) * 10) / 10} mm to go before one is due.`,
          },
          {
            plain: 'Water need coefficient',
            themed: 'Thirst',
            value: String(water.k_c),
            note: kC
              ? `${confidenceStatus(kC.confidence, kC.is_user_override).plain}. ${kC.source ? `Source: ${sourceKind(kC.source.kind)}.` : 'No source was consulted for it.'}`
              : 'This plant has no recorded coefficient; the engine used its default.',
          },
          {
            plain: 'Soil moisture sensor',
            value:
              water.sensor_override_pct != null
                ? `${water.sensor_override_pct}% — the sensor overrides the model`
                : 'None fitted',
            note:
              water.sensor_override_pct != null
                ? undefined
                : 'There is no soil-moisture hardware in the house, so nothing measures the soil to catch the model when it is wrong. The figures above are the only authority on watering this plant.',
          },
        ]
      : [],
  );

  function refresh() {
    void invalidate('moh:specimen');
  }
</script>

<div class="stack">
  <Card themed="The care profile" plain="Care values, with their sources" level={2}>
    {#if data.careValues.error}
      <StaleNotice plain="The care profile" asOf={null} reason={data.careValues.error} />
    {:else if !data.speciesId}
      <EmptyState
        icon="search"
        themed="Nothing to consult"
        plain="No care values yet"
        body="This plant has not been matched to a species, so no source has been read for it. Nothing has been guessed in the meantime."
      />
    {:else if careValues.length}
      <CareValueList
        values={careValues}
        specimenId={specimen.id}
        speciesId={data.speciesId}
        onsaved={refresh}
      />
    {:else}
      <EmptyState
        icon="book"
        themed="The sources were silent"
        plain="No care values were found"
        body="The sources consulted had nothing to say about this species. No value has been invented to fill the gap."
      />
    {/if}
  </Card>

  <Card themed="The rounds it keeps" plain="Watering schedule" level={2}>
    {#if data.rules.error}
      <StaleNotice plain="The care rules" asOf={null} reason={data.rules.error} />
    {:else if rules.length}
      <ul class="rules">
        {#each rules as rule (rule.id)}
          {@const strategy = CARE_STRATEGIES[rule.strategy] ?? {
            themed: rule.strategy,
            plain: rule.strategy,
          }}
          <li>
            <ListRow
              themed={strategy.themed}
              plain={`${TASK_TYPES[rule.task_type] ?? rule.task_type} — ${strategy.plain}`}
              meta={[
                rule.base_interval_days ? `Every ${rule.base_interval_days} days at base` : null,
                rule.amount_ml ? `${rule.amount_ml} ml` : null,
                rule.enabled ? 'Active' : 'Switched off',
              ]
                .filter(Boolean)
                .join(' · ')}
              icon="water"
            />
          </li>
        {/each}
      </ul>
      <p class="aside">
        Rules turn into dated tasks in Morning Rounds, where they are ticked off. Editing a rule
        from here is not built yet.
      </p>
    {:else}
      <EmptyState
        icon="water"
        themed="No rounds set"
        plain="No care rules for this plant"
        body="Nothing is scheduled for it. Rules are generated from the care profile, and a plant with no cited watering interval gets none — Morning Rounds names it rather than leaving it off silently."
      />
    {/if}
  </Card>

  <Card themed="What is owed" plain="Tasks for this plant" level={2}>
    {#if data.tasks.error}
      <StaleNotice plain="This plant's tasks" asOf={null} reason={data.tasks.error} />
    {:else if tasks.length}
      <ul class="rules">
        {#each tasks as task (task.id)}
          <li>
            <ListRow
              themed={task.title}
              plain={task.plain_title}
              meta={`${formatDate(task.due_at)} · ${task.status === 'satisfied' ? `already covered by ${task.satisfied_by ?? 'the weather'}` : task.status}`}
              icon={task.status === 'satisfied' ? 'rain' : 'water'}
            />
          </li>
        {/each}
      </ul>
      <p class="aside">
        Completing a task happens in <a href="/">Morning Rounds</a>, one at a time or a round at a
        time. These are read-only here.
      </p>
    {:else}
      <EmptyState
        icon="check"
        themed="Nothing owed today"
        plain="No tasks outstanding"
        body="Nothing is due for this plant right now."
      />
    {/if}
  </Card>

  <Card
    themed={specimen.is_outdoor ? 'Rain against sun' : 'By the calendar'}
    plain={specimen.is_outdoor ? 'Water balance' : 'Watering indoors'}
    level={2}
  >
    {#if !specimen.is_outdoor}
      <p>
        This plant is indoors. No rain reaches it and no evaporation figure applies, so its watering
        runs on the interval in the care profile above, adjusted for season and dormancy.
      </p>
      {#if kC}
        <p class="aside">
          Its water-need coefficient is still recorded, and is used if the plant is moved outdoors.
          <StatusPill status={confidenceStatus(kC.confidence, kC.is_user_override)} />
        </p>
      {/if}
    {:else if data.water.error}
      <StaleNotice plain="The water balance" asOf={null} reason={data.water.error} />
    {:else if water}
      {#if kC && (kC.confidence === 'unknown' || kC.source === null) && !kC.is_user_override}
        <p class="warn" role="note">
          <strong>This recommendation rests on an uncited number.</strong>
          The water need below has no source, and there is no soil sensor to check it against. Correct
          it in the care profile above if you know better — your correction wins over every source.
        </p>
      {/if}
      <p class="verdict">
        {#if water.is_due}
          <StatusPill status={STATUS.parched} />
        {:else}
          <StatusPill
            status={{ themed: 'Content for now', plain: 'No watering due', tone: 'sated' }}
          />
        {/if}
      </p>
      <div
        class="gauge"
        aria-hidden="true"
        style="--fill: {Math.min(
          100,
          Math.round((water.deficit_mm / Math.max(water.capacity_mm, 1)) * 100),
        )}%; --mark: {Math.min(
          100,
          Math.round((water.threshold_mm / Math.max(water.capacity_mm, 1)) * 100),
        )}%"
      ></div>
      <FactList facts={waterFacts} />
      {#if water.days.length}
        <p class="aside">
          The last {water.days.length} days are on record. The day-by-day chart arrives with the history
          charts in an earlier release.
        </p>
      {/if}
    {:else}
      <EmptyState
        icon="rain"
        themed="No reckoning yet"
        plain="No water balance for this plant"
        body="The engine has not produced a balance for it."
      />
    {/if}
  </Card>

  <Card
    themed="The frost watch"
    plain="Frost status"
    level={2}
    tone={frostAlerts.length ? 'danger' : 'plain'}
  >
    {#if data.frost.error}
      <StaleNotice plain="The frost lookahead" asOf={null} reason={data.frost.error} />
    {:else if !specimen.is_outdoor}
      <p>Indoors. The frost guard does not watch this plant while it stays there.</p>
    {:else if frostAlerts.length}
      <ul class="rules">
        {#each frostAlerts as alert (alert.id)}
          <li class="alert">
            <StatusPill status={STATUS.frostComing} />
            <p>
              The night of {formatDate(alert.night_of)} is forecast to fall to
              {alert.forecast_low_c} °C. This plant is warned below {alert.threshold_c} °C.
            </p>
            <p class="aside">
              {alert.action === 'bring_indoors'
                ? 'Bring it indoors before sunset.'
                : alert.action === 'cover'
                  ? 'Cover or protect it where it stands.'
                  : 'Watch it; no action is needed yet.'}
              {#if alert.advisory}<br />Advisory: {alert.advisory}{/if}
            </p>
          </li>
        {/each}
      </ul>
    {:else}
      <p>
        No frost alert within the 72-hour lookahead.
        {#if careValues.some((v) => v.field === 'min_temp_c')}
          {@const minTemp = careValues.find((v) => v.field === 'min_temp_c')}
          {#if minTemp}
            It is warned when the forecast low comes within 1.7 °C of
            {minTemp.value} °C — {confidenceStatus(
              minTemp.confidence,
              minTemp.is_user_override,
            ).plain.toLowerCase()}.
          {/if}
        {:else}
          No lowest safe temperature is recorded for it, so the guard has nothing to compare the
          forecast against. Set one in the care profile above.
        {/if}
      </p>
    {/if}
  </Card>

  <SeeAlso current="tending" specimenId={specimen.id} />
</div>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }
  .rules {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  .aside {
    margin: var(--moh-space-3) 0 0;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .warn {
    margin: 0 0 var(--moh-space-4);
    padding: var(--moh-space-3);
    border: 2px solid var(--moh-ailing);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-sunken);
    font-size: var(--moh-text-sm);
  }
  .verdict {
    margin: 0 0 var(--moh-space-3);
  }
  .gauge {
    position: relative;
    height: 0.75rem;
    margin-block-end: var(--moh-space-4);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: linear-gradient(
      to right,
      var(--moh-parched) 0 var(--fill),
      var(--moh-surface-sunken) var(--fill) 100%
    );
  }
  .gauge::after {
    content: '';
    position: absolute;
    inset-block: -2px;
    inset-inline-start: var(--mark);
    width: 2px;
    background: var(--moh-ink);
  }
  .alert p {
    margin: var(--moh-space-2) 0 0;
  }
</style>
