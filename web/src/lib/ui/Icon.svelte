<script lang="ts">
  import { ICONS, type IconName } from './icons';

  /** A 24×24 line icon stroked in `currentColor`. Decorative unless given a
   *  `title`: an icon is never the only thing carrying a meaning. */
  let {
    name,
    size = 20,
    title,
    strokeWidth = 1.6,
  }: { name: IconName; size?: number | string; title?: string; strokeWidth?: number } = $props();

  const spec = $derived.by(() => {
    const found = ICONS[name];
    if (!found) throw new Error(`Icon: no icon named "${name}".`);
    return found;
  });
</script>

<svg
  class="icon"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={strokeWidth}
  stroke-linecap="round"
  stroke-linejoin="round"
  role={title ? 'img' : undefined}
  aria-hidden={title ? undefined : 'true'}
  focusable="false"
>
  {#if title}<title>{title}</title>{/if}
  {#each spec.paths as d (d)}<path {d} />{/each}
</svg>

<style>
  .icon {
    flex: none;
    display: inline-block;
    vertical-align: -0.15em;
  }
</style>
