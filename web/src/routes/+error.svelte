<script lang="ts">
  /** The page the app shows when a load fails.
   *
   *  It lives at the root because that is where SvelteKit looks: an error
   *  raised in a layout's `load` is caught by the boundary *above* that layout,
   *  so a specimen that is not in the Register lands here rather than on the
   *  Specimen page. The message is whatever the load said — "No plant in the
   *  Register has that number" — because a number on its own tells nobody
   *  anything.
   */
  import { page } from '$app/stores';
  import { EmptyState, ListRow } from '$ui';

  const status = $derived($page.status);
  const detail = $derived($page.error?.message ?? '');

  const heading = $derived(
    status === 404
      ? { themed: 'No such entry', plain: 'That page is not here' }
      : { themed: 'The greenhouse is out of sorts', plain: 'Something went wrong' },
  );

  const body = $derived(
    detail ||
      (status === 404
        ? 'Nothing in the Ministry answers to that address.'
        : 'The app could not finish loading this page. Trying again often works.'),
  );
</script>

<svelte:head><title>{heading.plain} — The Ministry of Herbology</title></svelte:head>

<EmptyState
  icon={status === 404 ? 'search' : 'warning'}
  themed={heading.themed}
  plain={heading.plain}
  {body}
  level={1}
/>

<p class="code">Error {status}.</p>

<ul class="ways-back">
  <li>
    <ListRow
      themed="Morning Rounds"
      plain="Back to today"
      meta="What needs tending now"
      href="/"
      icon="water"
    />
  </li>
  <li>
    <ListRow
      themed="The Register"
      plain="Open the Register"
      meta="Every plant on the grounds"
      href="/register"
      icon="leaf"
    />
  </li>
</ul>

<style>
  .code {
    margin: var(--moh-space-4) 0 0;
    text-align: center;
    font-family: var(--moh-font-mono);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .ways-back {
    list-style: none;
    margin: var(--moh-space-6) 0 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
</style>
