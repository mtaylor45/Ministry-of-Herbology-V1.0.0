<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import Label from './Label.svelte';
  import { focusTrap } from './focusTrap';

  /** A modal dialog — a bottom sheet on a phone, a centred panel from 700px up.
   *
   *  Focus moves in when it opens, stays inside while it is open, and goes back
   *  to whatever opened it when it closes. Escape closes it when it may be
   *  dismissed. */
  let {
    open = $bindable(false),
    themed,
    plain,
    description,
    dismissible = true,
    variant = 'auto',
    closePlain = 'Close',
    onclose,
    children,
    footer,
  }: {
    open?: boolean;
    themed?: string;
    plain: string;
    /** A plain sentence describing the dialog, announced after its title. */
    description?: string;
    /** false for a dialog that must be answered: no Escape, no scrim tap. */
    dismissible?: boolean;
    variant?: 'auto' | 'sheet' | 'dialog';
    closePlain?: string;
    onclose?: () => void;
    children: Snippet;
    footer?: Snippet;
  } = $props();

  const id = $props.id();
  const titleId = `${id}-title`;
  const descId = $derived(description ? `${id}-desc` : undefined);

  function close() {
    if (!dismissible) return;
    open = false;
    onclose?.();
  }

  // Keep the page behind the sheet from scrolling under a thumb.
  $effect(() => {
    if (typeof document === 'undefined') return;
    const body = document.body;
    if (!open) return;
    const previous = body.style.overflow;
    body.style.overflow = 'hidden';
    return () => {
      body.style.overflow = previous;
    };
  });
</script>

{#if open}
  <div class="layer" data-variant={variant}>
    <button
      type="button"
      class="scrim"
      tabindex="-1"
      aria-hidden="true"
      onclick={close}
      data-dismissible={dismissible}
    ></button>
    <div
      class="panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descId}
      use:focusTrap={{ onescape: close }}
    >
      <header class="head">
        <h2 id={titleId}><Label {themed} {plain} display="below" where="Dialog" /></h2>
        {#if dismissible}
          <button type="button" class="close" onclick={close}>
            <Icon name="close" size={20} />
            <span class="visually-hidden">{closePlain}</span>
          </button>
        {/if}
      </header>
      {#if description}<p class="desc" id={descId}>{description}</p>{/if}
      <div class="body">{@render children()}</div>
      {#if footer}<footer class="foot">{@render footer()}</footer>{/if}
    </div>
  </div>
{/if}

<style>
  .layer {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }
  .scrim {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    background: var(--moh-scrim);
    cursor: pointer;
  }
  .scrim[data-dismissible='false'] {
    cursor: default;
  }
  .panel {
    position: relative;
    width: 100%;
    max-height: 90dvh;
    overflow-y: auto;
    padding: var(--moh-space-4);
    padding-bottom: calc(var(--moh-space-4) + env(safe-area-inset-bottom));
    background: var(--moh-surface-raised);
    color: var(--moh-ink);
    border: 1px solid var(--moh-border);
    border-radius: var(--moh-radius-lg) var(--moh-radius-lg) 0 0;
    box-shadow: var(--moh-shadow-floating);
    animation: rise var(--moh-motion-sheet) var(--moh-motion-ease);
  }
  @keyframes rise {
    from {
      transform: translateY(1.5rem);
      opacity: 0.6;
    }
  }
  .head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--moh-space-3);
  }
  h2 {
    margin: 0;
    font-size: var(--moh-text-xl);
  }
  .close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: var(--moh-tap);
    height: var(--moh-tap);
    background: none;
    border: none;
    color: var(--moh-ink-muted);
    cursor: pointer;
  }
  .desc {
    margin: var(--moh-space-2) 0 0;
    color: var(--moh-ink-muted);
  }
  .body {
    margin-top: var(--moh-space-3);
  }
  .foot {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--moh-space-2);
    margin-top: var(--moh-space-4);
  }

  /* From tablet width up it stops being a sheet and becomes a panel. */
  @media (min-width: 700px) {
    .layer[data-variant='auto'],
    .layer[data-variant='dialog'] {
      align-items: center;
    }
    .layer[data-variant='auto'] .panel,
    .layer[data-variant='dialog'] .panel {
      width: min(32rem, calc(100vw - 2 * var(--moh-space-8)));
      border-radius: var(--moh-radius-lg);
    }
  }
</style>
