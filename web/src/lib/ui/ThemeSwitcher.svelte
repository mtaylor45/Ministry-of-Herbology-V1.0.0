<script lang="ts">
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import type { IconName } from './icons';
  import { THEME_OPTIONS, applyThemeToDocument, readThemeChoice, type ThemeChoice } from './theme';

  /** Parchment, night greenhouse, or whatever the device says. Writes
   *  `data-theme` on the document element and remembers the choice. */
  let {
    choice = $bindable<ThemeChoice>('system'),
    themed = 'The light in the greenhouse',
    plain = 'Theme',
    onchange,
  }: {
    choice?: ThemeChoice;
    themed?: string;
    plain?: string;
    onchange?: (choice: ThemeChoice) => void;
  } = $props();

  const id = $props.id();
  const GLYPHS: Record<ThemeChoice, IconName> = {
    parchment: 'sun',
    greenhouse: 'moon',
    system: 'gear',
  };

  // Pick up what was stored last time, once, on the client.
  $effect(() => {
    if (typeof localStorage === 'undefined') return;
    choice = readThemeChoice(localStorage);
    applyThemeToDocument(choice);
  });

  function pick(next: ThemeChoice) {
    choice = next;
    applyThemeToDocument(next);
    onchange?.(next);
  }
</script>

<fieldset class="switcher">
  <legend><Label {themed} {plain} where="ThemeSwitcher" /></legend>
  <div class="options">
    {#each THEME_OPTIONS as option (option.choice)}
      <label class="option" data-selected={choice === option.choice}>
        <input
          type="radio"
          name={`${id}-theme`}
          value={option.choice}
          checked={choice === option.choice}
          onchange={() => pick(option.choice)}
        />
        <span class="face">
          <Icon name={GLYPHS[option.choice]} size={18} />
          <Label
            themed={option.themed}
            plain={option.plain}
            display="below"
            where="ThemeSwitcher"
          />
        </span>
      </label>
    {/each}
  </div>
</fieldset>

<style>
  .switcher {
    border: none;
    margin: 0;
    padding: 0;
  }
  legend {
    padding: 0 0 var(--moh-space-2);
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
    min-height: var(--moh-tap);
    cursor: pointer;
  }
  .option input {
    position: absolute;
    inset: 0;
    opacity: 0;
    margin: 0;
    cursor: inherit;
  }
  .face {
    display: inline-flex;
    align-items: center;
    gap: var(--moh-space-2);
    min-height: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-3);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius);
    background: var(--moh-surface-raised);
  }
  /* Selected is marked by a filled face and a thicker edge, not by hue alone. */
  .option[data-selected='true'] .face {
    background: var(--moh-selected);
    border-color: var(--moh-accent);
    box-shadow: inset 0 0 0 1px var(--moh-accent);
  }
  .option input:focus-visible + .face {
    outline: 3px solid var(--moh-accent);
    outline-offset: 2px;
  }
</style>
