<script lang="ts">
  /** The Almanac needs a site and could not find one.
   *
   *  Every forecast is a forecast *for somewhere*, and the client learns where
   *  from the `site_id` on a location — the contract has no endpoint that lists
   *  sites (raised with the maintainers in this release's pull request). When no
   *  location carries one, the weather is genuinely unanswerable, and saying so
   *  is better than showing a plausible sky. */
  import EmptyState from '$ui/EmptyState.svelte';

  let { reason = null }: { reason?: string | null } = $props();
</script>

<EmptyState
  icon="pin"
  themed="No grounds are registered"
  plain="The Almanac does not know where to look"
  body={reason ??
    'Every forecast is a forecast for somewhere, and no location in the register carries a site. Add a location in the Ministry Office and the weather will follow.'}
/>
