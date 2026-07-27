# Design system — CD tokens

Corporate design of the Antragsplattform (requirements **N1/N1a**). Source:
STUPA CD, primary color **British Racing Green**. Defined in
[`src/styles/tokens.scss`](./src/styles/tokens.scss) as CSS custom properties.

## Two levels

1. **Primitive** (`--c-*`) — the raw palette, independent of the theme. Do **not** use
   these directly in a component.
2. **Semantic** (`--color-*`, `--shadow-*`) — role-based tokens. Each theme (light and
   dark) maps them again. Use **only** these in a component.

Theme switch: the attribute `data-theme="light|dark"` on `<html>`, set by the
`ThemeService`. Each theme also sets `color-scheme`.

## Palette (primitive)

| Token | Value | Note |
|---|---|---|
| `--c-brg-700` | `#004225` | **British Racing Green** — core brand color |
| `--c-brg-50 … -900` | green scale | tints and shades |
| `--c-neutral-0 … -950` | warm neutral | surfaces and text |
| `--c-accent-500` | `#b08530` | bronze accent, use it sparingly |
| `--c-success/warning/danger/info-500` | — | status |

## Semantic tokens

| Token | Role |
|---|---|
| `--color-bg`, `--color-bg-elevated` | page background, raised background |
| `--color-surface`, `--color-surface-sunken` | cards, inset surfaces |
| `--color-border`, `--color-border-strong` | separators, input borders |
| `--color-text`, `--color-text-muted`, `--color-text-inverse` | text |
| `--color-primary`, `-hover`, `-active`, `-subtle`, `--color-on-primary` | primary action |
| `--color-focus-ring` | visible focus (WCAG 2.1 AA) |
| `--color-accent` | accent |
| `--color-success/warning/danger/info` (+ `-subtle`) | status (badge, toast) |
| `--shadow-sm/md/lg` | elevation |

`tokens.scss` holds the light and dark values under `:root[data-theme='light']` and
`:root[data-theme='dark']`.

## Typography

`--font-sans` = **Archivo**, a free grotesk (OFL, self-hosted). It replaces DIN on the web.
Weights 400/500/600/700. Scale `--fs-xs … --fs-3xl`, base 16 px.
`--font-mono` covers code and IDs. **DIN stays PDF-only** (pytex/T-20).

## More scales

- **Spacing** `--space-0 … --space-12` (4 px grid, wide white space).
- **Radius** `--radius-sm/md/lg/xl/pill`.
- **Motion** `--motion-fast/base` plus `--ease-standard`. Motion respects
  `prefers-reduced-motion`.
- **Layout** `--layout-max-width`, `--layout-header-height`, `--layout-gutter`.
- **Z-index** `--z-dropdown/sticky/dialog/toast`.

## UI kit

`shared/ui` — button, input, card, table, stepper, dialog, toast, badge.
The components are standalone and `OnPush`. They use semantic tokens only and cover the
a11y basics: labels, focus and ARIA.
Every component has one Jest test that uses the Angular Testing Library.

## Change or extend

- New color → add the primitive first, then map a semantic token for each theme.
- New font → change `--font-sans` only, plus the `@font-face` rule in `_fonts.scss`.
- Original STUPA assets → replace the files in `assets/logos` and keep the same names.
