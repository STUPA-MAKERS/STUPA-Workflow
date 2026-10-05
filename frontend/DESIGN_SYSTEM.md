# Design system — tokens and rules

The design system of the Antragsplattform. It has one accent colour (green `#72a384`),
neutral grey surfaces and two signal colours (warning, error). The fonts are IBM Plex Sans
and IBM Plex Mono. The ui-kit submodule (`vendor/ui-kit`, repo `STUPA-MAKERS/ui-kit`) holds
the tokens, the fonts, the breakpoints and the components:

- `vendor/ui-kit/src/styles/tokens.scss` — primitive and semantic tokens per theme
- `vendor/ui-kit/src/styles/fonts.scss` — `@font-face` rules of the self-hosted fonts
- `vendor/ui-kit/src/styles/base.scss` — reset, role type scale, text utilities
- `vendor/ui-kit/src/styles/_breakpoints.scss` — breakpoint mixins (no CSS output)
- `vendor/ui-kit/src/lib/breakpoints/breakpoints.ts` — the same breakpoints for code

`src/styles.scss` loads the kit styles (`@use 'fonts'`, `'tokens'`, `'base'`) and adds the
app utilities.

## Two levels

1. **Primitive** (`--c-*`) — the raw palette. A value for one theme has the theme in its
   name (`--c-light-c2`, `--c-dark-pt`). Do **not** use a primitive in a component.
2. **Semantic** (`--color-*`, `--shadow-*`) — role tokens. Each theme maps them again. Use
   **only** these in a component.

Theme switch: the attribute `data-theme="light|dark"` on `<html>`. `ThemeService` sets it.
Each theme also sets `color-scheme`.

The semantic **names** are stable. A redesign changes their values only, so a page that uses
`--color-primary` keeps working. One meaning changed: `--color-primary` is now the accent as
**text**. A fill (button, bar, dot, selected chip) uses `--color-accent` with
`--color-on-accent`, or `--color-selected` with `--color-on-selected` for a selection. Do not
use `--color-primary` or `--color-success` as a background, or the page shows a second green.
Do not use `--color-accent` as a text colour: it has less than 3:1 on the light surfaces. Text
in the accent uses `--color-accent-text`. The spec `core/theme/token-roles.spec.ts` checks
both rules.

## Palette (primitive)

| Role | Light | Dark | Note |
|---|---|---|---|
| bg | `#f6f7f5` | `#101211` | page background |
| c1 … c4 | `#ffffff` … `#d6dad5` | `#171a18` … `#323633` | surfaces, from low to high |
| on / onv / mut | `#191c1a` / `#4a504c` / `#666c68` | `#e2e5e2` / `#b3b8b4` / `#878d89` | text, muted text, captions |
| ol / olv | `#7a807c` / `#dcdfdb` | `#6f7571` / `#303431` | control edge, divider |
| accent | `#72a384` | `#72a384` | the one accent (fill) |
| on accent | `#0b1d12` | `#0b1d12` | text on the accent fill |
| pt | `#3c6a4d` | `#8dbb9d` | accent as text |
| pc / onpc | `#d6eadc` / `#0f2e1b` | `#21362a` / `#c3e3cd` | accent container |
| sel / onsel | `#e1eee5` / `#11301d` | `#243129` / `#e2efe6` | selected row or item |
| warn | `#8a5a00` | `#dcb065` | warning text |
| err | `#b3261e` | `#ee9b90` | error text, destructive action |

## Semantic tokens

| Token | Role |
|---|---|
| `--color-bg`, `--color-bg-elevated` | page background, dialog and menu surface |
| `--color-surface`, `--color-surface-sunken`, `--color-surface-raised` | box, filled field, opened panel |
| `--color-surface-1` … `--color-surface-4` | the four surface steps (c1 … c4) |
| `--color-border`, `--color-border-strong` | divider, control edge (3:1 for WCAG 1.4.11) |
| `--color-text`, `--color-text-muted`, `--color-text-subtle`, `--color-text-inverse` | text, secondary text, captions and field labels, text on an inverse surface |
| `--color-accent`, `--color-on-accent` | accent fill (main button, switch, progress) and the text on it |
| `--color-accent-text` = `--color-primary` | accent as text (links, text buttons, section headings) |
| `--color-accent-container`, `--color-on-accent-container` | accent tag |
| `--color-primary-hover`, `-active`, `-subtle`, `--color-on-primary` | older names, kept for callers |
| `--color-selected`, `--color-on-selected` | selected row, active chip, active rail item |
| `--color-focus-ring` | visible focus (WCAG 2.1 AA) |
| `--color-success` (= accent text), `--color-warning`, `--color-danger`, `--color-info` (+ `-subtle`) | status text |
| `--color-scrim` | backdrop behind a dialog |
| `--shadow-sm/md/lg`, `--shadow-elevated` | elevation; `elevated` for menus, popovers, FAB, selection bar |

`src/styles/contrast.spec.ts` in the kit checks the text pairs in both themes.

## Typography

`--font-sans` = **IBM Plex Sans** (400/500/600/700). `--font-mono` = **IBM Plex Mono**
(400/500) for amounts, short IDs, keys and code. Both are under the SIL Open Font License.
The kit ships them as `woff2` in a `latin` and a `latin-ext` subset. `angular.json` copies
them to `/assets/fonts`. The CSP allows `font-src 'self' data:` only, so never load a font
from Google Fonts or another CDN. **DIN stays PDF only** (typst render service).

Role scale (size / line height):

| Role | Token | Value | Used for |
|---|---|---|---|
| d2 | `--fs-d2` | 28 / 36 | page title (`h1`) |
| h1 | `--fs-h1` | 22 / 28 | section or dialog title (`h2`) |
| h2 | `--fs-h2` | 17 / 24 | sub-section (`h3`) |
| h3 | `--fs-h3` | 15 / 22 | list title, field value (`h4`) |
| body | `--fs-body` | 14 / 20 | body text |
| small | `--fs-small` | 12.5 / 18 | secondary lines |
| cap | `--fs-cap` | 11.5 / 16, uppercase | table headers, group labels |

The generic scale `--fs-xs … --fs-3xl` stays and follows the role values.

Text utilities (global): `.num` (tabular numbers), `.mono` (Plex Mono), `.ell` (one line
with an ellipsis), `.cap` (caption), `.kbd` (a key), `.sec` (section heading in accent text).

## Breakpoints

| Class | Width | Layout |
|---|---|---|
| phone | ≤ 768px | bottom bar, stacked cards, near-fullscreen dialogs |
| narrow | 769px – 1199px | navigation rail, a list and its detail as separate views |
| wide | ≥ 1200px | navigation rail, a list and its detail side by side |

The phone limit is the 768px rule that the app always used (`max-width: 768px`). The narrow
boards are 960px wide and show the list and the detail as separate views. For this reason
the list-detail split starts at 1200px.

In a stylesheet: `@use 'breakpoints' as bp;` and `@include bp.phone { … }` (also
`bp.narrow`, `bp.wide`, `bp.not-phone`, `bp.below-wide`). In code: `MEDIA.phone` with
`window.matchMedia`, or `widthClass(window.innerWidth)` from `@stupa-makers/ui-kit`.

## More scales

- **Spacing** `--space-0 … --space-12` (4px grid).
- **Radius** `--radius-sm` 6 (tag), `-md` 8 (chip), `-field` 14 (field, menu, toast),
  `-lg` 16 (table, grouped list), `-xl` 20 (box, card), `-2xl` 24 (dialog, sheet), `-pill`.
- **Controls** `--control-height-sm/-/-lg` = 32 / 40 / 52px, `--field-height` = 56px.
- **Motion** `--motion-fast/base` plus `--ease-standard`. Motion respects
  `prefers-reduced-motion`.
- **Layout** `--layout-max-width`, `--layout-header-height`, `--layout-gutter`. The app shell sets
  `--layout-header-height` to 0 (the rail replaced the top bar) and adds `--rail-width` 96px,
  `--bottom-bar-height` 80px, `--main-pad-top`/`--main-pad-bottom` (the block padding of the main
  region) and, on a phone, `--app-bottom-inset` (how far up the bottom bar reaches).
- **Z-index** `--z-dropdown/sticky/dialog/toast`.

## Rules

These rules are binding for every page.

- **One accent.** Only the accent is green. Everything else is grey or a signal colour.
- **A status is coloured text.** No dot and no pill. Use `app-badge` with a status variant
  (`success`, `warning`, `danger`, `info`, `primary`). `app-badge [color]` (the configured
  colour of a flow state) is a status too: text in that colour, made darker or lighter per
  theme until it has AA contrast.
- **A tag is a feature, not a status** (NÖ, Stimmrecht, Pool, Pflichtrolle, fest). Use
  `app-badge` with `neutral` or `accent`.
- **A destructive action is an outlined red button** (`app-button variant="danger"`). Never
  fill it.
- **Fill or center.** A content block fills the width or is centered. Do not leave empty
  space on the right.
- **No noise text.** Show only text that has a function. Do not add hint or filler
  sentences.
- **Input fields have no shadow and no edge.** A field is filled (surface 2, radius 14).
  Focus draws a 2px accent line inside the field. A field outside the kit (a formly type, a
  native `.field__control`) uses the same look; the kit mixins are in `_field.scss`
  (`@use 'field' as f;`).
- **Long names get an ellipsis and a `title`** with the full text (`.ell`).
- **Avatars only for persons.** Do not put an initials circle on a row of a thing (an
  application, a meeting).

## UI kit components

Import from `@stupa-makers/ui-kit`. All components are standalone and `OnPush`. They use
semantic tokens only and have labels, focus and ARIA. Each one has Jest tests with the
Angular Testing Library, and `a11y.spec.ts` runs axe over them.

- `app-button` — looks `fill`, `tonal`, `outlined`, `text`, `danger`, `fab`. Sizes `sm`
  32, `md` 40, `lg` 52, pill shape. `iconOnly` gives a round icon button, `ariaPressed` an
  on/off toggle. The older names `primary`, `success` (= fill), `secondary` (= tonal),
  `ghost` (= text) and `danger-outline` (= danger) stay as aliases.
- `app-switch` — `role="switch"` for a setting that applies at once.
- `app-segmented` — a radio group in one row (Ausgabe/Einnahme, Anwesend/Abwesend). `width="equal"` makes the segments equal (list views), `width="fill"` lets them share the width of a form or a column; an option can carry a `count` (invoice segments), and `[check]="false"` leaves out the check mark where the column is narrow.
- `app-tabs` — a tab bar with optional counts (Antrag | Verlauf 4).
- `app-input`, `app-select`, `app-datepicker`, `app-time-input`, `app-currency-input` —
  filled fields with the label inside the box. `app-checkbox` — an 18px box.
- `app-dialog` — a sheet (radius 24), title, actions at the right. Below 768px it is
  near-fullscreen.
- `app-data-table`, `app-table` — the table frame (radius 16, cut line and tongue for
  sideways scrolling), 56px rows, caption header, selected row in `--color-selected`. Below
  768px the data table shows cards.
- `app-filter-bar` — a chip that turns to `--color-selected` while a filter is active.
- `app-icon` — line icons on a 24px grid as inline SVG (`stroke="currentColor"`).
  `ICON_NAMES` lists the set.
- `app-badge`, `app-card`, `app-stepper`, `app-config-diff`, toast, loading overlay.

## Change or extend

- A new colour: add the primitive for both themes first, then map a semantic token.
- A ui-kit change goes to the kit repo first (a PR against its `development` branch). Then
  move the submodule pointer of the app.
- Original STUPA assets: replace the files in `assets/logos` and keep the same names.
