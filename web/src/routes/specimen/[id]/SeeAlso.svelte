<script lang="ts">
  /** The cross-links every facet carries to the other three.
   *
   *  One component, one list, so no facet can quietly grow a different set —
   *  cross-linking is the feature, not a nicety. A facet that is listed before
   *  it is built says so in its own row rather than being hidden — a missing
   *  facet the reader can see is better than one they cannot. The journal was
   *  that row from an earlier release to an earlier release; none is today.
   */
  import { Card, ListRow } from '$ui';
  import { seeAlso, type FacetId } from './facets';

  let { current, specimenId }: { current: FacetId; specimenId: string } = $props();

  const links = $derived(seeAlso(current, specimenId));
</script>

<Card themed="See also" plain="The other facets of this plant" level={2}>
  <ul class="links">
    {#each links as link (link.id)}
      <li>
        <ListRow
          themed={link.themed}
          plain={link.plain}
          meta={link.built ? link.blurb : `${link.blurb}. This link leads nowhere today.`}
          href={link.href}
          icon={link.icon}
        />
      </li>
    {/each}
  </ul>
</Card>

<style>
  .links {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-2);
  }
</style>
