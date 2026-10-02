<script lang="ts">
  /** The Almanac: what the weather is about to do, and what it has done.
   *
   *  Three views, three URLs. A tab that only exists in component state cannot
   *  be linked to, cannot be reopened where it was left, and is one more thing
   *  to get wrong with a thumb; plain links work before any JavaScript does.
   */
  import { page } from '$app/stores';

  let { children } = $props();

  const VIEWS = [
    { href: '/almanac', themed: 'The ten days', plain: '10-day forecast', exact: true },
    { href: '/almanac/today', themed: 'This day', plain: 'Hourly, today', exact: false },
    { href: '/almanac/history', themed: 'The record', plain: 'History', exact: false },
  ];

  const isCurrent = (view: (typeof VIEWS)[number], pathname: string) =>
    view.exact ? pathname === view.href : pathname.startsWith(view.href);
</script>

<svelte:head><title>The Almanac — The Ministry of Herbology</title></svelte:head>

<header class="head">
  <h1>The Almanac <span class="plain">Weather and conditions</span></h1>
</header>

<nav class="views" aria-label="Almanac views">
  <ul>
    {#each VIEWS as view (view.href)}
      <li>
        <a href={view.href} aria-current={isCurrent(view, $page.url.pathname) ? 'page' : undefined}>
          <span class="themed">{view.themed}</span>
          <span class="plain">{view.plain}</span>
        </a>
      </li>
    {/each}
  </ul>
</nav>

{@render children()}

<style>
  .head h1 {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--moh-space-2);
    margin: 0 0 var(--moh-space-4);
    font-family: var(--moh-font-display);
  }
  .plain {
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-sm);
  }
  .views ul {
    display: flex;
    gap: var(--moh-space-2);
    margin: 0 0 var(--moh-space-6);
    padding: 0;
    list-style: none;
    overflow-x: auto;
  }
  .views a {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    color: inherit;
    text-decoration: none;
    white-space: nowrap;
  }
  /* Selected is carried by the underline and the bold weight as well as the
   * colour — and `aria-current` says it outright. */
  .views a[aria-current='page'] {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
    box-shadow: inset 0 -3px 0 var(--moh-accent);
    font-weight: 600;
  }
  .views .themed {
    font-family: var(--moh-font-display);
  }
</style>
