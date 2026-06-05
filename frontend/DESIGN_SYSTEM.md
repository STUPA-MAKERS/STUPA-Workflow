# Design-System — CD-Tokens

Corporate Design der Antragsplattform (requirements **N1/N1a**). Quelle:
HSRT/STUPA-CD, Primärfarbe **British Racing Green**. Definiert in
[`src/styles/tokens.scss`](./src/styles/tokens.scss) als CSS-Custom-Properties.

## Zwei Ebenen

1. **Primitive** (`--c-*`) — rohe Palette, theme-unabhängig. **Nicht** direkt in
   Komponenten verwenden.
2. **Semantic** (`--color-*`, `--shadow-*`) — rollenbasierte Tokens, pro Theme
   (Light/Dark) neu gemappt. **Ausschließlich** diese in Komponenten nutzen.

Theme-Umschaltung: Attribut `data-theme="light|dark"` auf `<html>` (gesetzt vom
`ThemeService`). `color-scheme` wird je Theme mitgesetzt.

## Palette (Primitive)

| Token | Wert | Hinweis |
|---|---|---|
| `--c-brg-700` | `#004225` | **British Racing Green** — Markenkern |
| `--c-brg-50 … -900` | grün-Skala | Tints/Shades |
| `--c-neutral-0 … -950` | warm-neutral | Flächen/Text |
| `--c-accent-500` | `#b08530` | Bronze-Akzent (sparsam) |
| `--c-success/warning/danger/info-500` | — | Status |

## Semantic-Tokens

| Token | Rolle |
|---|---|
| `--color-bg`, `--color-bg-elevated` | Seiten-/erhöhter Hintergrund |
| `--color-surface`, `--color-surface-sunken` | Karten / eingelassene Flächen |
| `--color-border`, `--color-border-strong` | Trennlinien / Eingabe-Rahmen |
| `--color-text`, `--color-text-muted`, `--color-text-inverse` | Text |
| `--color-primary`, `-hover`, `-active`, `-subtle`, `--color-on-primary` | Primäraktion |
| `--color-focus-ring` | Sichtbarer Fokus (WCAG 2.1 AA) |
| `--color-accent` | Akzent |
| `--color-success/warning/danger/info` (+ `-subtle`) | Status (Badge/Toast) |
| `--shadow-sm/md/lg` | Elevation |

Light- und Dark-Werte sind in `tokens.scss` unter
`:root[data-theme='light']` bzw. `:root[data-theme='dark']` gepflegt.

## Typografie

`--font-sans` = **Archivo** (freie Grotesk, OFL, self-hosted; DIN-Ersatz im Web).
Gewichte 400/500/600/700. Skala `--fs-xs … --fs-3xl`, Basis 16 px.
`--font-mono` für Code/IDs. **DIN bleibt PDF-only** (pytex/T-20).

## Weitere Skalen

- **Spacing** `--space-0 … --space-12` (4-px-Raster, viel Weißraum).
- **Radius** `--radius-sm/md/lg/xl/pill`.
- **Motion** `--motion-fast/base` + `--ease-standard`; respektiert
  `prefers-reduced-motion`.
- **Layout** `--layout-max-width`, `--layout-header-height`, `--layout-gutter`.
- **Z-Index** `--z-dropdown/sticky/dialog/toast`.

## UI-Kit

`shared/ui` — Button, Input, Card, Table, Stepper, Dialog, Toast, Badge.
Standalone, `OnPush`, nur Semantic-Tokens, a11y-Basics (Labels, Fokus, ARIA).
Jede Komponente hat einen Jest + Angular-Testing-Library-Test.

## Anpassen / Erweitern

- Neue Farbe → erst Primitive ergänzen, dann Semantic-Token je Theme mappen.
- Font tauschen → nur `--font-sans` (und `@font-face` in `_fonts.scss`).
- HSRT/STUPA-Originalassets → Dateien in `assets/logos` ersetzen (gleiche Namen).
