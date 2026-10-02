<script lang="ts">
  /** Calendar feeds — the earlier feed management.
   *
   *  A feed URL is a password: anyone holding it can read that feed. So:
   *
   *  - the URL is shown **once**, from the response to the `POST` that made
   *    it, with a copy control, and is forgotten when the reader says they
   *    have it or leaves the page;
   *  - the list is read in the browser through `readFeeds()`, which strips
   *    every URL before this component sees the data — a list row has no URL
   *    field to render;
   *  - no URL goes into an error message, a status line or the console.
   *    The copy control reports "Copied", never what was copied;
   *  - revoking a feed names that feed in the confirmation, and touches no
   *    other (the scheduler's route rotates that one token and only that one).
   */
  import { onMount, tick } from 'svelte';
  import { Button, Card, Dialog, EmptyState, MemberPicker, SelectField, TextField } from '$ui';
  import type { Member } from '$ui';
  import { createFeed, readFeeds, reason, revokeFeed } from './api';
  import {
    TASK_TYPE_WORDS,
    feedBody,
    filterSummary,
    sortFeeds,
    type CreatedFeed,
    type ListedFeed,
    type TaskType,
  } from './office';
  import { formatDate } from '../shared/labels';

  let {
    members,
    locationName,
  }: {
    members: Member[];
    locationName: (id: string) => string | undefined;
  } = $props();

  // ------------------------------------------------------------ the list

  let feeds = $state<ListedFeed[] | null>(null);
  let listError = $state<string | null>(null);

  async function refresh() {
    try {
      feeds = sortFeeds(await readFeeds(fetch));
      listError = null;
    } catch (cause) {
      listError = reason(cause);
    }
  }
  onMount(refresh);

  const memberName = (id: string | null) =>
    (id && members.find((m) => m.id === id)?.name) || 'a member no longer listed';

  // ------------------------------------------------------------ creating

  let name = $state('');
  let memberId = $state('');
  let outdoor = $state<'' | 'true' | 'false'>('');
  let taskTypes = $state<TaskType[]>([]);
  let creating = $state(false);
  let createError = $state<string | null>(null);
  let nameError = $state<string | undefined>(undefined);

  /** The one place a URL lives, and only until it is dismissed. */
  let created = $state<CreatedFeed | null>(null);
  let copied = $state<string | null>(null);
  let createdEl = $state<HTMLElement | null>(null);

  const outdoorOptions = [
    { value: '', plain: 'Indoor and outdoor plants' },
    { value: 'false', plain: 'Indoor plants only' },
    { value: 'true', plain: 'Outdoor plants only' },
  ];

  async function create(event: SubmitEvent) {
    event.preventDefault();
    nameError = name.trim() ? undefined : 'Give the feed a name, so it can be told apart later.';
    createError = memberId ? null : 'Choose whose calendar this feed is for.';
    if (nameError || createError) return;
    creating = true;
    try {
      created = await createFeed(feedBody({ name, memberId, outdoor, taskTypes }), fetch);
      copied = null;
      name = '';
      taskTypes = [];
      outdoor = '';
      await refresh();
      await tick();
      createdEl?.focus();
    } catch (cause) {
      // `reason()` speaks of status codes and paths — never of a URL, and the
      // POST's path carries no token.
      createError = reason(cause);
    } finally {
      creating = false;
    }
  }

  async function copy(which: 'webcal' | 'https') {
    if (!created) return;
    const url = which === 'webcal' ? created.webcal_url : created.https_url;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      copied = which === 'webcal' ? 'Calendar address copied.' : 'Web address copied.';
    } catch {
      copied = 'This browser would not copy it. Select the address above and copy it by hand.';
    }
  }

  function forget() {
    created = null;
    copied = null;
  }

  // ------------------------------------------------------------ revoking

  let revoking = $state<ListedFeed | null>(null);
  let revokeOpen = $state(false);
  let revokeBusy = $state(false);
  let revokeError = $state<string | null>(null);
  let revokedNote = $state<string | null>(null);

  function askRevoke(feed: ListedFeed) {
    revoking = feed;
    revokeError = null;
    revokeOpen = true;
  }

  async function confirmRevoke() {
    if (!revoking) return;
    revokeBusy = true;
    revokeError = null;
    const feed = revoking;
    try {
      await revokeFeed(feed.id, fetch);
      if (created?.id === feed.id) forget();
      revokedNote = `“${feed.name}” is revoked. Calendars subscribed to it stop updating; every other feed is unchanged.`;
      revokeOpen = false;
      revoking = null;
      await refresh();
    } catch (cause) {
      revokeError = reason(cause);
    } finally {
      revokeBusy = false;
    }
  }
</script>

<Card themed="Almanac subscriptions" plain="Calendar feeds" level={2}>
  <p class="warning">
    <strong>A feed address is a password.</strong> Anyone who has it can read that calendar. It is shown
    once, when the feed is made, and never again. To share a calendar with someone, make them their own
    feed — then it can be revoked without touching yours.
  </p>

  {#if created}
    <section class="created" tabindex="-1" bind:this={createdEl} aria-labelledby="created-heading">
      <h3 id="created-heading">“{created.name}” is ready — copy its address now</h3>
      <p>
        Add it to Google, Apple or any calendar that subscribes to a URL. This is the only time this
        screen shows it.
      </p>
      <label class="url">
        <span>Calendar address (webcal)</span>
        <input
          type="text"
          readonly
          value={created.webcal_url}
          onfocus={(e) => e.currentTarget.select()}
        />
      </label>
      <div class="row-actions">
        <Button
          variant="quiet"
          plain="Copy the calendar address"
          icon="check"
          onclick={() => copy('webcal')}
        />
      </div>
      {#if created.https_url}
        <label class="url">
          <span>Web address (https), for calendars that will not take webcal</span>
          <input
            type="text"
            readonly
            value={created.https_url}
            onfocus={(e) => e.currentTarget.select()}
          />
        </label>
        <div class="row-actions">
          <Button
            variant="quiet"
            plain="Copy the web address"
            icon="check"
            onclick={() => copy('https')}
          />
        </div>
      {/if}
      <p class="status" role="status">{copied ?? ''}</p>
      <Button plain="I have copied it — hide the address" onclick={forget} />
    </section>
  {/if}

  {#if revokedNote}<p class="status" role="status">{revokedNote}</p>{/if}

  <h3 class="sub">Feeds</h3>
  {#if listError}
    <p class="note" role="alert">The feeds could not be read: {listError}</p>
  {:else if feeds === null}
    <p class="note">Reading the feeds…</p>
  {:else if feeds.length === 0}
    <EmptyState
      icon="bell"
      plain="No calendar feeds yet"
      body="Make one below to see the household's tasks in a calendar app."
    />
  {:else}
    <ul class="feeds">
      {#each feeds as feed (feed.id)}
        <li class="feed" data-revoked={feed.revoked}>
          <div class="text">
            <span class="name">{feed.name}</span>
            <span class="meta"
              >For {memberName(feed.member_id)} · {filterSummary(feed.filters, locationName)}</span
            >
            <span class="meta">
              {#if feed.revoked}
                Revoked — its address no longer works.
              {:else if feed.last_rendered_at}
                Last read by a calendar {formatDate(feed.last_rendered_at)}.
              {:else}
                No calendar has read it yet.
              {/if}
            </span>
          </div>
          {#if !feed.revoked}
            <Button
              variant="destructive"
              plain="Revoke “{feed.name}”"
              onclick={() => askRevoke(feed)}
            />
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <h3 class="sub">Make a feed</h3>
  <form class="make" onsubmit={create}>
    <TextField
      name="feed-name"
      plain="Feed name"
      hint="Say where it goes, e.g. “Mark’s phone” or “House-sitter, August”."
      error={nameError}
      required
      bind:value={name}
    />
    <MemberPicker
      {members}
      bind:value={memberId}
      themed="Whose almanac"
      plain="Whose calendar it is"
      remember={false}
    />
    <SelectField
      name="feed-outdoor"
      plain="Which plants"
      options={outdoorOptions}
      bind:value={outdoor}
    />
    <fieldset class="types">
      <legend>Which tasks <span class="meta">(none ticked means every kind)</span></legend>
      {#each Object.entries(TASK_TYPE_WORDS) as [value, words] (value)}
        <label class="type">
          <input type="checkbox" {value} bind:group={taskTypes} />
          <span>{words}</span>
        </label>
      {/each}
    </fieldset>
    <p class="note">
      Pushing to Google Calendar or CalDAV is set up by the operator, not here; a feed made here is
      a subscription address.
    </p>
    <Button
      type="submit"
      themed="Bind a new almanac"
      plain="Make the feed"
      icon="plus"
      loading={creating}
      busyPlain="Making the feed…"
    />
    {#if createError}<p class="note" role="alert">{createError}</p>{/if}
  </form>
</Card>

<Dialog
  bind:open={revokeOpen}
  plain={revoking ? `Revoke “${revoking.name}”?` : 'Revoke this feed?'}
  description="Calendars subscribed to this feed stop updating, and its address stops working for good. No other feed is affected."
  onclose={() => (revoking = null)}
>
  {#if revokeError}<p class="note" role="alert">{revokeError}</p>{/if}
  {#snippet footer()}
    <Button variant="quiet" plain="Keep it" onclick={() => (revokeOpen = false)} />
    <Button
      variant="destructive"
      plain={revoking ? `Revoke “${revoking.name}”` : 'Revoke'}
      loading={revokeBusy}
      busyPlain="Revoking…"
      onclick={confirmRevoke}
    />
  {/snippet}
</Dialog>

<style>
  .warning {
    margin: 0 0 var(--moh-space-4);
    padding: var(--moh-space-3) var(--moh-space-4);
    border-inline-start: 4px solid var(--moh-gold-line);
    background: var(--moh-surface-sunken);
    color: var(--moh-ink);
  }
  .created {
    display: grid;
    gap: var(--moh-space-3);
    margin-bottom: var(--moh-space-6);
    padding: var(--moh-space-4);
    border: 2px solid var(--moh-accent);
    border-radius: var(--moh-radius);
    background: var(--moh-surface);
  }
  .created:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .created h3,
  .created p {
    margin: 0;
  }
  .url {
    display: grid;
    gap: var(--moh-space-1);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .url input {
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    font-family: var(--moh-font-mono);
    font-size: var(--moh-text-sm);
    background: var(--moh-field);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    width: 100%;
  }
  .url input:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .row-actions {
    display: flex;
    gap: var(--moh-space-2);
  }
  .sub {
    margin: var(--moh-space-6) 0 var(--moh-space-3);
    font-size: var(--moh-text-lg);
  }
  .feeds {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
  .feed {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-3);
    align-items: center;
    justify-content: space-between;
    padding: var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface);
  }
  .feed[data-revoked='true'] {
    background: var(--moh-surface-sunken);
  }
  .text {
    display: grid;
    gap: var(--moh-space-1);
    min-width: 0;
  }
  .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .meta,
  .note,
  .status {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .note,
  .status {
    margin: var(--moh-space-2) 0;
  }
  .status:empty {
    margin: 0;
  }
  .make {
    display: grid;
    gap: var(--moh-space-4);
    justify-items: stretch;
  }
  .types {
    margin: 0;
    padding: 0;
    border: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
    gap: var(--moh-space-2);
  }
  .types legend {
    padding: 0;
    margin-bottom: var(--moh-space-2);
    font-weight: 600;
  }
  .type {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
    min-height: var(--moh-tap);
    cursor: pointer;
  }
  .type input {
    width: 1.25rem;
    height: 1.25rem;
    accent-color: var(--moh-accent);
  }
  .type input:focus-visible {
    outline: 2px solid var(--moh-accent);
    outline-offset: 2px;
  }
</style>
