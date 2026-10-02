# The component library — the design system

Everything J, the maps module and the journal need to build a screen without writing a control. Import
from `$ui`:

```svelte
<script lang="ts">
  import { Button, Card, ListRow, TaskCheckbox, StatusPill, STATUS } from '$ui';
</script>

<Card themed="Morning Rounds" plain="Due today">
  <TaskCheckbox
    themed="The basil thirsts"
    plain="Water the basil"
    meta="Kitchen sill — due today"
  />
  <Button themed="Tend to it" plain="Water now" icon="water" />
</Card>
```

See every component in both themes at once: `npm run dev`, then `/gallery`.

## What is here

| Component                                                      | For                                                                |
| -------------------------------------------------------------- | ------------------------------------------------------------------ |
| `Button`                                                       | primary, quiet and destructive actions; `loading` and `disabled`   |
| `Card`                                                         | a titled panel; `level` keeps page headings nesting properly       |
| `ListRow`                                                      | one row of a list, sized for a thumb; link, button or plain row    |
| `TaskCheckbox`                                                 | one-tap and batch task completion — the app's most-used control    |
| `TextField` `NumberField` `SelectField` `Toggle` `SearchInput` | field primitives                                                   |
| `Dialog`                                                       | modal sheet on a phone, panel from 700px; traps and restores focus |
| `EmptyState` `Skeleton` `StaleNotice`                          | nothing yet, loading, and out-of-date                              |
| `Icon` `StatusPill` `ThemeSwitcher` `Nav`                      | icon set, status, theme, navigation                                |
| `MemberPicker`                                                 | who is acting — name and role, remembered per device               |

Helpers worth knowing: `selectionState`/`toggleAll`/`toggleOne` (batch selection),
`formatAsOf`/`staleSentence` (how old is this?), `requirePair`/`plainFirst`
(the pairing rule), `applyTheme`/`readThemeChoice`, `focusTrap`,
`readRememberedMember`/`rememberMember`/`initialMember` (who acted last, per
device, never required to be stored).

## The accessibility audit

`npm run a11y` is the earlier exit criterion: axe-core over every route, both themes,
375×812 and 1024×768, reduced-motion both ways on Morning Rounds. It fails on
a serious or critical WCAG violation and prints everything else. See
[`a11y/README.md`](./a11y/README.md) for how to start the API and the build
for it; the route list is `AUDIT_ROUTES` in `a11y/audit.ts`, one place, for the test suite
to reuse.

## Paired labels, and the ink the plain half takes

Every component renders its labels through `Label`, which paints the plain half
with `--moh-plain-ink`. At the root that is `--moh-ink-muted`. **Anything that
paints its own background under a label re-declares it** in the same rule:

```css
.btn[data-variant='primary'] {
  background: var(--moh-accent);
  color: var(--moh-accent-ink);
  --moh-plain-ink: var(--moh-accent-ink);
}
```

Skip that and the plain half keeps the page's muted ink on a colour nobody
measured — which is exactly how a 1.26:1 pairing shipped and stayed shipped.
`contrast.test.ts` now walks these stylesheets and fails on a fill that is
neither declared nor listed in `FILLS_WITHOUT_A_LABEL` with a reason.

## What a tick means

`TaskCheckbox` takes `meaning`:

| `meaning`              | The tick is                   | Ticked row shows | Struck through |
| ---------------------- | ----------------------------- | ---------------- | -------------- |
| `completion` (default) | the act itself                | "Done"           | yes            |
| `selection`            | gathering the row for a batch | "Selected"       | no             |

Morning Rounds wants `selection`: attribution is chosen at completion, so the tick cannot be the completion, and a row struck through before
anybody has watered anything is a lie. `donePlain` still overrides the word for
a list that needs its own.

## The five rules these components keep for you

1. **Every themed string is paired with a plain one.** Components take `themed`
   and `plain`; `plain` is required and the themed half never renders alone. Pass
   a themed string without a plain one and the component throws in dev.
2. **Touch targets are at least 44px** — `--moh-tap`, with list rows at
   `--moh-row`. The app is used outdoors, one-handed, in gloves.
3. **Status is never carried by colour alone.** Errors say "Error", completed
   tasks say "Done", switches say "On" or "Off", selection is announced with
   `aria-pressed`/`aria-current`.
4. **Focus is visible, and dialogs give it back.** `Dialog` traps Tab, closes on
   Escape when it may be dismissed, and returns focus to whatever opened it.
5. **Whimsy at moments only**, and everything animated honours
   `prefers-reduced-motion` — in the stylesheet, not in script, so it holds
   before hydration. Three moments, all on the `--moh-motion-*` tokens: a page
   turn between the facets of one plant, the seal's entrance on the sidebar,
   and a task row settling under the tap that completed it.
6. **Disabled is still readable.** A disabled control is a flat, sunken face
   in the muted ink (6.06:1 on parchment, 10.13:1 on greenhouse), not the
   whole control at 55% opacity — which on the night greenhouse composited the
   gold fill to an olive nobody measured, with "nothing selected yet" the
   least readable line on Morning Rounds. WCAG exempts an inactive control;
   the person reading why it is inactive is not exempt.

## Changing a colour

Tokens live in `tokens.css`, in two theme blocks. There is **no
`prefers-color-scheme` block**: `parchment` is the default whatever the device
prefers, and `contrast.test.ts` asserts the block has not crept back.
Dark is a choice made in the switcher, remembered, and "match my device" is
still one of the three options.

`contrast.test.ts` checks every pair against WCAG AA in both themes, walks the
components for colours painted under a label, keeps full-strength gold out of
anything that carries meaning, and keeps `theme.ts` and `app.html` agreeing
about the storage key, the default and the theme colours. Add a token, add its
pairs. If a colour fails, change the colour — never the threshold.

### The three brasses

Antique Gold at full strength (`--moh-gold-decor`, `#B89A5A`) measures
1.74–2.30:1 on the light surfaces. On parchment it may **decorate** and nothing
else: never text, never a border or ring that is the only indicator of focus,
selection or state. Use `--moh-gold-line` (`#877241`, ≥3:1) for borders and
rules, and `--moh-gold-ink` (`#6E5C36`, ≥4.5:1) for gold set as text. On the
night greenhouse all three are the same colour, because there gold already
passes. The gallery shows the three side by side.

### Type

`--moh-font-display` is self-hosted Cormorant Garamond (`fonts.css`,
`web/static/fonts/`) with the system serif stack behind it — never a font CDN. `--moh-font-body` stays system-first. `--moh-font-ui` is a system
sans for metadata, dates, form labels and system messages, which is what tells
the plain half of a paired label from the themed one where tone cannot.
