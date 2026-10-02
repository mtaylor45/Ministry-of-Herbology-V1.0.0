<script lang="ts">
  import { page } from '$app/stores';
  import { onNavigate } from '$app/navigation';
  import OfflineNotice from '../../app-shell/OfflineNotice.svelte';
  import { transitionKind } from '../../app-shell/motion';

  /** Bottom bar on mobile, sidebar from 900px up. Five sections, per the plan. */
  const SECTIONS = [
    { href: '/', themed: 'Morning Rounds', plain: 'Today' },
    { href: '/register', themed: 'The Register', plain: 'Inventory' },
    { href: '/grounds', themed: 'The Grounds', plain: 'Maps' },
    { href: '/almanac', themed: 'The Almanac', plain: 'Weather' },
    { href: '/office', themed: 'Ministry Office', plain: 'Settings' },
  ];

  const isCurrent = (href: string, pathname: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href);

  // A page turn between the facets of one plant (guide §18). This only says
  // *that* a turn is happening, by marking the document for its duration; how
  // it moves, and that it does not move under prefers-reduced-motion, is
  // base.css — the stylesheet, not a script, so the preference holds before
  // hydration. A browser without view transitions simply navigates.
  onNavigate((navigation) => {
    if (typeof document === 'undefined' || !('startViewTransition' in document)) return;
    const kind = transitionKind(navigation.from?.url.pathname, navigation.to?.url.pathname);
    if (!kind) return;
    const root = document.documentElement;
    root.dataset.transition = kind;
    return new Promise((resolve) => {
      const transition = document.startViewTransition(async () => {
        resolve();
        await navigation.complete;
      });
      void transition.finished.finally(() => {
        delete root.dataset.transition;
      });
    });
  });
</script>

<!-- The offline notice rides with the section bar: this is the one component
     of the shell every page mounts, so the shell can say "you are offline" on
     every screen without the layout file (the app's screens') changing. -->
<OfflineNotice />

<nav aria-label="Sections">
  <!-- The one mark, on the sidebar only: the bottom bar has no room
       for it at 375 wide, and there the app icon carries it. Decorative — the
       section names are the navigation. It arrives once per load, slowly,
       which is the one entrance the guide asks a seal to make (§22). -->
  <img class="seal" src="/seal.svg" alt="" width="72" height="72" aria-hidden="true" />
  <ul>
    {#each SECTIONS as section (section.href)}
      <li>
        <a
          href={section.href}
          aria-current={isCurrent(section.href, $page.url.pathname) ? 'page' : undefined}
        >
          <span class="themed">{section.themed}</span>
          <span class="plain">{section.plain}</span>
        </a>
      </li>
    {/each}
  </ul>
</nav>

<style>
  nav {
    position: fixed;
    inset: auto 0 0 0;
    background: var(--moh-surface-raised);
    border-top: 1px solid var(--moh-border);
    padding-bottom: env(safe-area-inset-bottom);
    z-index: 10;
  }
  ul {
    display: flex;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    flex: 1;
    min-width: 0;
  }
  a {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    min-height: var(--moh-tap);
    /* 2px, not the 4px grid: five tabs in 375px leaves 71px each, and
       "Morning Rounds" needs 67 of them. A label that wraps here makes the bar
       taller than the padding the page reserves for it, and the last card on
       every screen disappears underneath. */
    padding: var(--moh-space-2) 2px;
    color: var(--moh-ink-muted);
    text-decoration: none;
    text-align: center;
    min-width: 0;
  }
  /* A longer section name added later shortens rather than reflows the bar. */
  .themed,
  .plain {
    max-width: 100%;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  a[aria-current='page'] {
    color: var(--moh-accent);
    box-shadow: inset 0 2px 0 var(--moh-accent);
  }
  .themed {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-xs);
  }
  /* §15: small uppercase labels, wide tracking. These are two or three words on
     a tab, so uppercase costs nothing here and the tracking buys legibility.

     The 0.75 opacity this replaced faded `--moh-ink-muted` toward the surface
     underneath it, which is a composited colour no token test can measure. A
     nav label is the last text in the app that should be guessed at. */
  .plain {
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-xs);
    letter-spacing: var(--moh-tracking-meta);
    text-transform: uppercase;
  }

  .seal {
    display: none;
  }
  @keyframes arrive {
    from {
      opacity: 0;
      transform: translateY(6px) scale(0.96);
    }
  }

  @media (min-width: 900px) {
    nav {
      inset: 0 auto 0 0;
      width: 14rem;
      border-top: none;
      border-right: 1px solid var(--moh-border);
    }
    /* Atmospheric, so the long token. Reduced motion clamps every
       animation in tokens.css, so under it the seal is simply there. */
    .seal {
      display: block;
      margin: var(--moh-space-6) auto 0;
      animation: arrive var(--moh-motion-atmospheric) var(--moh-motion-ease) both;
    }
    ul {
      flex-direction: column;
      padding-top: var(--moh-space-4);
    }
    a {
      flex-direction: row;
      justify-content: flex-start;
      gap: var(--moh-space-2);
      padding-inline: var(--moh-space-4);
    }
    a[aria-current='page'] {
      box-shadow: inset 3px 0 0 var(--moh-accent);
    }
    .themed {
      font-size: var(--moh-text-base);
    }
  }
</style>
