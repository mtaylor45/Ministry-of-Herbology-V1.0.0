<script lang="ts">
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import {
    initialMember,
    memberById,
    readRememberedMember,
    rememberMember,
    roleLabel,
    type Member,
  } from './member';

  /** Who is acting. A radio group of the household's members, each with their
   *  name and role, that remembers the last choice on this device and emits
   *  the member id.
   *
   *  A radio group rather than a select: there are three people in a
   *  household, not thirty, and three faces side by side are one tap each,
   *  outdoors, in gloves — a select is two taps and a popup. Native radios
   *  underneath, so arrow keys move between them and a screen reader reads
   *  "Keeper, radio button, 1 of 3, checked" with nothing added. */
  let {
    members,
    value = $bindable(''),
    themed = 'Whose hands',
    plain = 'Acting as',
    hint,
    emptyPlain = 'The household has no members on record, so nothing can be attributed.',
    remember = true,
    disabled = false,
    onchange,
  }: {
    members: readonly Member[];
    /** The chosen member's id; `''` is nobody. */
    value?: string;
    themed?: string;
    plain?: string;
    hint?: string;
    /** Shown instead of the options when `members` is empty. */
    emptyPlain?: string;
    /** Remember the choice on this device, and start on it next time. */
    remember?: boolean;
    disabled?: boolean;
    onchange?: (id: string, member: Member) => void;
  } = $props();

  const id = $props.id();
  const hintId = $derived(hint ? `${id}-hint` : undefined);

  // Pick up what this device remembered, once, on the client — but never
  // over a choice the screen already made.
  $effect(() => {
    if (!remember || value) return;
    const start = initialMember(members, readRememberedMember());
    if (start) value = start;
  });

  function pick(member: Member) {
    value = member.id;
    if (remember) rememberMember(member.id);
    onchange?.(member.id, member);
  }

  const chosen = $derived(memberById(members, value));
</script>

<fieldset class="picker" {disabled} aria-describedby={hintId}>
  <legend><Label {themed} {plain} where="MemberPicker" /></legend>
  {#if members.length}
    <div class="options" role="presentation">
      {#each members as member (member.id)}
        {@const role = roleLabel(member.role)}
        {@const selected = member.id === value}
        <label class="option" data-selected={selected}>
          <input
            type="radio"
            name="{id}-member"
            value={member.id}
            checked={selected}
            {disabled}
            onchange={() => pick(member)}
          />
          <span class="face">
            <span class="mark" aria-hidden="true">
              {#if selected}<Icon name="check" size={16} />{/if}
            </span>
            <span class="who">
              <span class="name">{member.name}</span>
              <span class="role"><Label themed={role.themed} plain={role.plain} /></span>
            </span>
          </span>
        </label>
      {/each}
    </div>
    <!-- The choice, in words, for anyone the filled face does not reach. -->
    <p class="chosen" aria-live="polite">
      {#if chosen}
        Acting as {chosen.name}.
      {:else}
        Nobody chosen yet.
      {/if}
    </p>
  {:else}
    <p class="empty">{emptyPlain}</p>
  {/if}
  {#if hint}<p class="hint" id={hintId}>{hint}</p>{/if}
</fieldset>

<style>
  .picker {
    border: none;
    margin: 0;
    padding: 0;
    min-width: 0;
  }
  legend {
    padding: 0 0 var(--moh-space-2);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
  }
  .option {
    display: inline-flex;
    position: relative;
    flex: 1 1 8rem;
    min-width: 0;
    min-height: var(--moh-tap);
    cursor: pointer;
  }
  .picker:disabled .option {
    cursor: not-allowed;
  }
  .option input {
    position: absolute;
    inset: 0;
    opacity: 0;
    margin: 0;
    cursor: inherit;
  }
  .face {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
    width: 100%;
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-raised);
    transition: background-color var(--moh-motion-quick) var(--moh-motion-ease);
  }
  /* Selected is a filled face, a thicker edge, a tick and a sentence — never a
     hue on its own. */
  .option[data-selected='true'] .face {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
    box-shadow: inset 0 0 0 1px var(--moh-accent);
  }
  .option input:focus-visible + .face {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }
  .picker:disabled .face {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
  }
  .mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 1.25rem;
    height: 1.25rem;
    border: 1px solid var(--moh-gold-line);
    border-radius: 50%;
    color: var(--moh-accent);
  }
  .option[data-selected='true'] .mark {
    border-color: var(--moh-accent);
  }
  .who {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    font-family: var(--moh-font-display);
    font-size: var(--moh-text-lg);
    font-weight: 500;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .role {
    font-size: var(--moh-text-xs);
  }
  .chosen,
  .hint,
  .empty {
    margin: var(--moh-space-2) 0 0;
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
</style>
