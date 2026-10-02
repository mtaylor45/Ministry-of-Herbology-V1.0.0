<script lang="ts">
  /** The Ministry Office — settings, honestly.
   *
   *  Each section says what it is and what it is not: integrations as the hub's hub
   *  reports them, the locations and the household as the inventory API serves them (read
   *  here, not edited — the contract has no route that adds a member, and the
   *  location editor is not in this slot), the calendar feeds, and backups,
   *  which are the operator's job and are described rather than run.
   */
  import { Card, EmptyState, StaleNotice, roleLabel } from '$ui';
  import type { PageData } from './$types';
  import PageTitle from '../shared/PageTitle.svelte';
  import { KIND_WORDS, sortLocations } from '../register/register';
  import { SUN_EXPOSURE } from '../specimen/[id]/labels';
  import Feeds from './Feeds.svelte';
  import { ROLE_WORDS, integrationView, sortIntegrations } from './office';

  let { data }: { data: PageData } = $props();

  const now = new Date();
  const members = $derived(data.members.value ?? []);
  const locations = $derived(sortLocations(data.locations.value ?? []));
  const plantCount = (n: number | undefined) => `${n ?? 0} ${n === 1 ? 'plant' : 'plants'}`;
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name;
</script>

<svelte:head><title>Ministry Office — The Ministry of Herbology</title></svelte:head>

<PageTitle
  themed="Ministry Office"
  plain="Settings — integrations, places, household, calendars, backups"
/>

<div class="stack">
  <Card themed="Correspondents" plain="Integrations" level={2}>
    <p class="note">
      What the hub says about each connected service. Weather is not reported here: the Almanac says
      how fresh its own forecast is.
    </p>
    {#if data.integrations.state === 'not-served'}
      <EmptyState
        icon="gear"
        plain="Integration health is not reported yet"
        body="This deployment's API does not serve the hub's integration list yet, so nothing here says whether Home Assistant or anything else is answering. That is not the same as all being well."
      />
    {:else if data.integrations.state === 'failed'}
      <StaleNotice plain="Integration health" asOf={null} reason={data.integrations.reason} />
    {:else if data.integrations.rows.length === 0}
      <EmptyState
        icon="gear"
        plain="Nothing is connected"
        body="No integrations are configured. The app runs on weather and your own observations; connecting Home Assistant adds soil sensors — the deployment guide, §11."
      />
    {:else}
      <ul class="list">
        {#each sortIntegrations(data.integrations.rows, now) as row (row.id)}
          {@const view = integrationView(row, now)}
          <li class="item" data-tone={view.tone}>
            <div class="head">
              <span class="name">{row.name}</span>
              <span class="word" data-tone={view.tone}>{view.word}</span>
            </div>
            <p class="detail">{view.detail}</p>
            {#if view.error}
              <p class="detail">Its last error, as it gave it: <q class="error">{view.error}</q></p>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </Card>

  <Card themed="The grounds and rooms" plain="Locations" level={2}>
    <p class="note">
      Read-only here. Zones are drawn on <a href="/grounds">the Grounds</a>; adding or renaming a
      location from this screen is not built yet.
    </p>
    {#if data.locations.error}
      <StaleNotice plain="The locations" asOf={null} reason={data.locations.error} />
    {:else if locations.length === 0}
      <EmptyState
        icon="pin"
        plain="No locations yet"
        body="No rooms, beds or zones are recorded."
      />
    {:else}
      <ul class="list">
        {#each locations as location (location.id)}
          <li class="item">
            <div class="head">
              <span class="name">{location.name}</span>
              <span class="meta">
                {KIND_WORDS[location.kind] ?? location.kind}, {location.is_outdoor
                  ? 'outdoors'
                  : 'indoors'}
              </span>
            </div>
            <p class="detail">
              {plantCount(location.specimen_count)}{#if location.specimen_count}{' — '}<a
                  href="/register?location_id={location.id}">see them in the Register</a
                >{/if}.
              {#if location.sun_exposure && location.sun_exposure !== 'unknown'}
                {SUN_EXPOSURE[location.sun_exposure] ?? location.sun_exposure}.
              {/if}
            </p>
          </li>
        {/each}
      </ul>
    {/if}
  </Card>

  <Card themed="The household" plain="Members" level={2}>
    <p class="note">
      Everyone shares one sign-in and picks their name when they act, so the record says who.
      Members are added by the operator; this screen lists them.
    </p>
    {#if data.members.error}
      <StaleNotice plain="The household" asOf={null} reason={data.members.error} />
    {:else if members.length === 0}
      <EmptyState
        icon="seedling"
        plain="No members recorded"
        body="Nobody is on record, so nothing can be attributed to anyone."
      />
    {:else}
      <ul class="list">
        {#each members as member (member.id)}
          {@const role = roleLabel(member.role)}
          <li class="item">
            <div class="head">
              <span class="name">{member.name}</span>
              <span class="meta">{ROLE_WORDS[member.role] ?? member.role} — {role.plain}</span>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </Card>

  <Feeds {members} {locationName} />

  <Card themed="The archive" plain="Backups" level={2}>
    <p>
      Backups are run by whoever operates this installation, not from this screen. On the server,
      <code>make backup</code> dumps the database and archives the three picture volumes together; a dump
      without the pictures, or the pictures without the dump, is not a recovery.
    </p>
    <p class="note">
      How to take one, prove it restores, and restore for real: the deployment guide,
      <code>docs/deploy/README.md</code> §13 “Backup and restore”. A backup on the same disk as the database
      is not a backup.
    </p>
  </Card>
</div>

<style>
  .stack {
    display: grid;
    gap: var(--moh-space-6);
  }
  .note {
    margin: 0 0 var(--moh-space-4);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  a {
    color: var(--moh-ink);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  a:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  code {
    font-family: var(--moh-font-mono);
    font-size: 0.95em;
    overflow-wrap: anywhere;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  .item {
    padding: var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface);
  }
  /* Something needing attention carries a thicker rule *and* its word; the
     rule is never the only signal. A set-up step gets no warning rule at all. */
  .item[data-tone='warn'] {
    border-inline-start: 4px solid var(--moh-ink);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-1) var(--moh-space-3);
    align-items: baseline;
    justify-content: space-between;
  }
  .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .meta,
  .detail {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .detail {
    margin: var(--moh-space-1) 0 0;
  }
  .word {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    font-weight: 600;
    color: var(--moh-ink);
  }
  .error {
    font-family: var(--moh-font-mono);
    color: var(--moh-ink);
    overflow-wrap: anywhere;
  }
</style>
