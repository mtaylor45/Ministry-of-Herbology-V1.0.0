<script lang="ts">
  import '$ui/base.css';
  import Nav from '$ui/Nav.svelte';

  let { children } = $props();
</script>

<a class="skip-link" href="#main">Skip to content</a>
<Nav />
<main id="main" tabindex="-1">
  {@render children()}
</main>

<style>
  main {
    max-width: 48rem;
    margin: 0 auto;
    padding: var(--moh-space-6) var(--moh-space-4);
    /* The section bar is fixed to the bottom of the phone, so the last card on
       a long page needs room to clear it — the Almanac's views are the first
       screens long enough to end underneath it. */
    padding-bottom: calc(var(--moh-space-12) + env(safe-area-inset-bottom));
  }
  @media (min-width: 900px) {
    main {
      margin-left: 14rem;
      padding-bottom: var(--moh-space-6);
    }
  }
</style>
