<script lang="ts">
  /** A placeholder while something loads. It says what is loading, out loud —
   *  a screen reader cannot see a grey bar shimmer. */
  let {
    lines = 3,
    width = '100%',
    height = '1rem',
    plain = 'Loading…',
    rounded = false,
  }: {
    lines?: number;
    width?: string;
    height?: string;
    /** What is being fetched: "Loading the Register…". */
    plain?: string;
    /** A circle instead of a bar, for avatars and plate thumbnails. */
    rounded?: boolean;
  } = $props();

  const rows = $derived(Array.from({ length: Math.max(1, lines) }, (_, index) => index));
</script>

<div class="skeleton" role="status" aria-busy="true">
  <span class="visually-hidden">{plain}</span>
  {#each rows as row (row)}
    <span
      class="bar"
      class:rounded
      aria-hidden="true"
      style="width: {row === rows.length - 1 && rows.length > 1 ? '60%' : width}; height: {height}"
    ></span>
  {/each}
</div>

<style>
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
  }
  .bar {
    display: block;
    background: var(--moh-skeleton);
    border-radius: var(--moh-radius);
    /* A slow breath rather than a sweep: it is a hint, not a performance. */
    animation: breathe 1600ms ease-in-out infinite;
  }
  .bar.rounded {
    border-radius: 50%;
  }
  @keyframes breathe {
    50% {
      opacity: 0.55;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .bar {
      animation: none;
      opacity: 0.8;
    }
  }
</style>
