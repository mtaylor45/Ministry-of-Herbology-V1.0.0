/** Button state, kept out of the component so it can be tested plainly. */

export type ButtonVariant = 'primary' | 'quiet' | 'destructive';

export interface ButtonState {
  disabled?: boolean;
  loading?: boolean;
}

/** A loading button stays focusable — it is about to become useful again. */
export function buttonIsInert({ disabled, loading }: ButtonState): boolean {
  return Boolean(disabled || loading);
}

/** The attributes a button carries for a given state. */
export function buttonAttrs(variant: ButtonVariant, state: ButtonState) {
  const loading = Boolean(state.loading);
  const disabled = Boolean(state.disabled);
  return {
    'data-variant': variant,
    'data-state': loading ? 'loading' : disabled ? 'disabled' : 'ready',
    // A disabled button leaves the tab order; a loading one keeps its place so
    // focus is not thrown to the top of the page mid-task.
    disabled: disabled && !loading ? true : undefined,
    'aria-disabled': loading ? ('true' as const) : undefined,
    'aria-busy': loading ? ('true' as const) : undefined,
  };
}
