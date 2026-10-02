<script lang="ts">
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import { buttonAttrs, buttonIsInert, type ButtonVariant } from './button';
  import type { IconName } from './icons';
  import { requirePair } from './pairing';

  /** The only button in the app. Primary, quiet and destructive; loading and
   *  disabled states; never smaller than a 44px touch target. */
  let {
    variant = 'primary',
    type = 'button',
    themed,
    plain,
    icon,
    loading = false,
    disabled = false,
    full = false,
    busyPlain = 'Working…',
    onclick,
    ...rest
  }: {
    variant?: ButtonVariant;
    type?: 'button' | 'submit' | 'reset';
    themed?: string;
    plain?: string;
    icon?: IconName;
    loading?: boolean;
    disabled?: boolean;
    /** Full width, for the primary action at the bottom of a sheet. */
    full?: boolean;
    /** What a screen reader hears while the button is busy. */
    busyPlain?: string;
    onclick?: (event: MouseEvent) => void;
    [key: string]: unknown;
  } = $props();

  // A button's label always goes through Label, so the pairing rule has no way
  // around it: there is no children snippet to smuggle a themed word through.
  const label = $derived(requirePair(themed, plain, 'Button'));

  const attrs = $derived(buttonAttrs(variant, { disabled, loading }));

  function handleClick(event: MouseEvent) {
    if (buttonIsInert({ disabled, loading })) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    onclick?.(event);
  }
</script>

<button {type} class="btn" class:full {...attrs} {...rest} onclick={handleClick}>
  {#if loading}
    <span class="spinner" aria-hidden="true"></span>
    <span class="visually-hidden">{busyPlain}</span>
  {:else if icon}
    <Icon name={icon} size={18} />
  {/if}
  <Label {themed} plain={label} where="Button" />
</button>

<style>
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--moh-space-2);
    min-height: var(--moh-tap);
    min-width: var(--moh-tap);
    padding: var(--moh-space-2) var(--moh-space-4);
    border-radius: var(--moh-radius);
    border: 1px solid transparent;
    font-family: var(--moh-font-body);
    font-size: var(--moh-text-base);
    line-height: 1.2;
    cursor: pointer;
    transition: background-color var(--moh-motion-quick) var(--moh-motion-ease);
  }
  .btn.full {
    width: 100%;
  }

  /* A filled variant says which ink the plain half of its label takes. Left to
     the page default it stays `--moh-ink-muted`, which is 1.26:1 on the green
     and 1.01:1 on the gold — the pairing this fix exists for. */
  .btn[data-variant='primary'] {
    background: var(--moh-accent);
    color: var(--moh-accent-ink);
    --moh-plain-ink: var(--moh-accent-ink);
  }
  .btn[data-variant='primary']:hover:not([data-state='disabled']) {
    background: var(--moh-accent-hover);
  }

  .btn[data-variant='quiet'] {
    background: transparent;
    color: var(--moh-accent);
    border-color: var(--moh-gold-line);
  }
  .btn[data-variant='quiet']:hover:not([data-state='disabled']) {
    background: var(--moh-surface-sunken);
  }

  .btn[data-variant='destructive'] {
    background: var(--moh-danger);
    color: var(--moh-danger-ink);
    --moh-plain-ink: var(--moh-danger-ink);
  }
  .btn[data-variant='destructive']:hover:not([data-state='disabled']) {
    background: var(--moh-danger-hover);
  }

  /* Disabled and loading are told apart by shape as well as by tone: the
     loading button keeps its fill and carries a spinner; the disabled one is a
     flat, sunken face in the page's muted ink.

     It used to dim the whole control to 55% opacity. On the night greenhouse
     that composited the gold fill down to an olive nobody measured, with the
     midnight ink still on top of it — "Mark done — nothing selected yet" is
     the one line a disabled button exists to say, and it was the least
     readable thing on Morning Rounds. WCAG exempts an inactive control from
     the contrast threshold; the earlier dark-mode walk did not. The plain half goes
     back to the page's ink here (`inherit`, because this face *is* a page
     surface), which `contrast.test.ts` measures at 6.06:1 and 10.13:1. */
  .btn[data-state='disabled'] {
    background: var(--moh-surface-sunken);
    color: var(--moh-ink-muted);
    border-color: var(--moh-border);
    --moh-plain-ink: inherit;
    cursor: not-allowed;
  }
  .btn[data-state='loading'] {
    cursor: progress;
  }

  .spinner {
    width: 1em;
    height: 1em;
    border-radius: 50%;
    border: 2px solid currentColor;
    border-top-color: transparent;
    animation: spin 900ms linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* Reduced motion: the spinner stops turning and pulses its opacity instead,
     so "busy" is still visible without movement. */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation: none;
      border-top-color: currentColor;
      opacity: 0.6;
    }
  }
</style>
