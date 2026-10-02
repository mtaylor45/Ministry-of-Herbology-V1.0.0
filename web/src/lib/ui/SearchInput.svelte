<script lang="ts">
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';

  /** The Register's search box. The label can be hidden visually but is always
   *  there; the clear button is a full touch target, not a 10px cross. */
  let {
    value = $bindable(''),
    themed,
    plain = 'Search',
    placeholder,
    hideLabel = false,
    disabled = false,
    name = 'q',
    clearPlain = 'Clear the search',
    oninput,
    onsubmit,
  }: {
    value?: string;
    themed?: string;
    plain?: string;
    placeholder?: string;
    /** Hide the label visually; it is still announced. */
    hideLabel?: boolean;
    disabled?: boolean;
    name?: string;
    clearPlain?: string;
    oninput?: (event: Event) => void;
    onsubmit?: (value: string) => void;
  } = $props();

  const id = $props.id();
  const labelId = `${id}-label`;

  function submit(event: SubmitEvent) {
    event.preventDefault();
    onsubmit?.(value);
  }

  function clear() {
    value = '';
    oninput?.(new Event('input'));
  }
</script>

<!-- The form is a search landmark, and a landmark without a name is one a
     screen reader lists as "search, search, search" on a page with several;
     it borrows its label, so a page that searches two things says which. -->
<form class="search" role="search" aria-labelledby={labelId} onsubmit={submit}>
  <label for={id} id={labelId} class:visually-hidden={hideLabel}>
    <Label {themed} {plain} where="SearchInput" />
  </label>
  <div class="box">
    <span class="glyph" aria-hidden="true"><Icon name="search" size={18} /></span>
    <input
      {id}
      {name}
      {placeholder}
      {disabled}
      {oninput}
      class="control"
      type="search"
      autocomplete="off"
      bind:value
    />
    {#if value}
      <button type="button" class="clear" onclick={clear}>
        <Icon name="close" size={18} />
        <span class="visually-hidden">{clearPlain}</span>
      </button>
    {/if}
  </div>
</form>

<style>
  .search {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-1);
  }
  label {
    font-size: var(--moh-text-sm);
  }
  .box {
    position: relative;
    display: flex;
    align-items: center;
  }
  .glyph {
    position: absolute;
    inset-inline-start: var(--moh-space-3);
    display: flex;
    color: var(--moh-ink-muted);
    pointer-events: none;
  }
  .control {
    width: 100%;
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-tap) var(--moh-space-2) var(--moh-space-8);
    background: var(--moh-field);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: 999px;
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-base);
  }
  /* The platform's own clear affordance is tiny; ours is a real target. */
  .control::-webkit-search-cancel-button {
    display: none;
  }
  .clear {
    position: absolute;
    inset-inline-end: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--moh-tap);
    height: var(--moh-tap);
    background: none;
    border: none;
    color: var(--moh-ink-muted);
    cursor: pointer;
  }
</style>
