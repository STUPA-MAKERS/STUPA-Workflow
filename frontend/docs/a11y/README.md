# Barrierefreiheit (a11y) — T-43

Ziel: **WCAG 2.1 AA** (requirements **N3**, SOLL; nicht formal BITV-zertifiziert)
für die in Welle 1/2 gebauten Views und das UI-Kit.

## Automatisierte Prüfungen (laufen in CI)

| Check | Datei | Deckt ab |
|-------|-------|----------|
| axe — UI-Primitive | `src/app/shared/ui/a11y.spec.ts` | Button, Input, Select, Checkbox, Datepicker, Badge, Card, Stepper, Table, **Dialog**, Vote-Bars, Toast |
| axe — Kern-Views | `src/app/a11y-views.spec.ts` | Shell-Landmarks (anon + auth), Apply-Wizard, Live-Vote, **Beamer**, 403/404 |
| Kontrast (deterministisch) | `src/styles/contrast.spec.ts` | WCAG 1.4.3 (Text ≥4.5) + 1.4.11 (Non-Text ≥3) über alle CD-Token-Paare, **Light + Dark** |
| i18n-Parität DE/EN | `src/app/core/i18n/translations.spec.ts` | Vollständigkeit beider Locales (bereits vorhanden) |

`@axe-core` läuft via **`jest-axe`** in jsdom. `color-contrast` ist dort nicht
berechenbar (kein Layout) und daher in axe deaktiviert — Kontraste werden statt-
dessen deterministisch gegen die Design-Tokens geprüft (`contrast.spec.ts`), was
in CI ohne Browser läuft und bei Token-Regressionen sofort rot wird.

## Was T-43 ergänzt/korrigiert hat

- **Fokus-Management im Dialog** (`shared/ui/dialog`): Fokus wandert beim Öffnen
  in den Dialog, **Focus-Trap** für Tab/Shift+Tab, Restore auf das auslösende
  Element beim Schließen (WCAG 2.1.2 / 2.4.3).
- **Kontrast-Tokens** (`styles/tokens.scss`):
  - `--color-text-muted` (Light) `#6e756f → #696f6a` — muted-Text auf bg jetzt
    ≥4.5:1 (vorher 4.45).
  - `--color-border-strong` (Control-Rahmen) Light `#c7ccc8 → #828a84`, Dark
    `#3c443e → #646f68` — Input/Select/Button-Grenzen jetzt ≥3:1 (WCAG 1.4.11);
    der dekorative `--color-border` (Divider/Karten) bleibt unangetastet.

## Bereits in Welle 1/2 vorhanden (durch die neuen Tests abgesichert)

Skip-Link, semantische Landmarks (`header/nav/main/footer`), `<html lang>` sync
bei Sprachwechsel, sichtbarer Fokus-Ring (`:focus-visible`),
`prefers-reduced-motion`-Reset, native Form-Controls mit `<label for>` +
`aria-describedby` + `role="alert"`, Live-Regionen (`role="status"`/`aria-live`)
für Verbindungs-/Vote-Status, `role="progressbar"` an den Vote-Balken,
`role="dialog"` + `aria-modal` + `aria-labelledby`.

## Visueller Nachweis (Vorher/Nachher, Light + Dark, Fokus)

Erzeugt headless via `~/.claude/fe-visual` (Xvfb-frei, niemals `:10.0`).
Montagen in diesem Verzeichnis; Einzel-Screenshots (28 Stück) unter
`~/antragsplattform-shots/t43/`.

- `a11y-focus.png` — Skip-Link + sichtbarer Fokus-Ring (Light/Dark)
- `a11y-home-light.png`, `a11y-home-dark.png`
- `a11y-apply-light.png` — Control-Rahmen-Kontrast
- `a11y-voting-light.png`, `a11y-beamer-dark.png`
