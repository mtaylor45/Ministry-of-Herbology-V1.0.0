/** The Ministry of Herbology component library.
 *
 * Everything another parts of the project needs to build a screen without writing its
 * own controls. Import from `$ui`:
 *
 *     import { Button, TaskCheckbox, STATUS } from '$ui';
 *
 * House rules baked into these components:
 *   - every themed string is paired with a plain one, and the themed half never
 *     renders alone;
 *   - touch targets are at least 44px;
 *   - status is never carried by colour alone;
 *   - focus is visible, dialogs trap it and give it back;
 *   - motion only at moments, and never against `prefers-reduced-motion`.
 */

export { default as Button } from './Button.svelte';
export { default as Card } from './Card.svelte';
export { default as Dialog } from './Dialog.svelte';
export { default as EmptyState } from './EmptyState.svelte';
export { default as Field } from './Field.svelte';
export { default as Icon } from './Icon.svelte';
export { default as Label } from './Label.svelte';
export { default as ListRow } from './ListRow.svelte';
export { default as MemberPicker } from './MemberPicker.svelte';
export { default as Nav } from './Nav.svelte';
export { default as NumberField } from './NumberField.svelte';
export { default as SearchInput } from './SearchInput.svelte';
export { default as SelectField } from './SelectField.svelte';
export { default as Skeleton } from './Skeleton.svelte';
export { default as StaleNotice } from './StaleNotice.svelte';
export { default as StatusPill } from './StatusPill.svelte';
export { default as TaskCheckbox } from './TaskCheckbox.svelte';
export { default as TextField } from './TextField.svelte';
export { default as ThemeSwitcher } from './ThemeSwitcher.svelte';
export { default as Toggle } from './Toggle.svelte';

export { buttonAttrs, buttonIsInert, type ButtonVariant } from './button';
export { FOCUSABLE_SELECTOR, focusTrap, focusable, resolveTrapTarget } from './focusTrap';
export { ICONS, ICON_NAMES, type IconName, type IconSpec } from './icons';
export { describedBy, uid } from './ids';
export {
  MEMBER_STORAGE_KEY,
  ROLE_LABELS,
  initialMember,
  memberById,
  readRememberedMember,
  rememberMember,
  roleLabel,
  type Member,
} from './member';
export { hasThemed, plainFirst, requirePair, type Paired, type PlainDisplay } from './pairing';
export {
  CHECKED_PLAIN,
  nextSelectAll,
  selectionState,
  selectionSummary,
  toggleAll,
  toggleOne,
  type CheckMeaning,
  type CheckState,
} from './selection';
export { formatAsOf, staleSentence, type Timestamp } from './stale';
export { STATUS, type Status, type StatusKey } from './status';
export {
  DEFAULT_THEME_CHOICE,
  THEMES,
  THEME_COLORS,
  THEME_OPTIONS,
  THEME_STORAGE_KEY,
  applyTheme,
  applyThemeToDocument,
  isThemeChoice,
  readThemeChoice,
  resolveTheme,
  type ThemeChoice,
  type ThemeName,
} from './theme';
export type { SelectOption } from './types';
