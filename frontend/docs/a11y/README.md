# Barrierefreiheit (a11y) — T-43

Ziel: **WCAG 2.1 AA** (requirements **N3**, SOLL; nicht formal BITV-zertifiziert)
für die in Welle 1/2 gebauten Views und das UI-Kit.

## Automatisierte Prüfungen (laufen in CI)

| Check | Datei | Deckt ab |
|-------|-------|----------|
| axe — UI-Primitive | `src/app/shared/ui/a11y.spec.ts` | Button, Input, Select, Checkbox, Datepicker, Badge, Card, Stepper, Table, **Dialog**, Vote-Bars, Toast |
| axe — Kern-Views | `src/app/a11y-views.spec.ts` | Shell-Landmarks (anon + auth), Apply-Wizard, Live-Vote, **Beamer**, 403/404, **Admin** (Home, Users, Flow-Editor, Branding) |
| Kontrast (deterministisch) | `src/styles/contrast.spec.ts` | WCAG 1.4.3 (Text ≥4.5) + 1.4.11 (Non-Text ≥3) über alle CD-Token-Paare inkl. **Badge-Chips** (Status/muted auf `*-subtle`), **Light + Dark** |
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
  - `--color-text-muted` (Light) `#6e756f → #666c67` — muted-Text jetzt ≥4.5:1
    auf bg **und surface-sunken** (Badge `neutral`, vorher 4.49).
  - `--color-border-strong` (Control-Rahmen) Light `#c7ccc8 → #828a84`, Dark
    `#3c443e → #646f68` — Input/Select/Button-Grenzen jetzt ≥3:1 (WCAG 1.4.11);
    der dekorative `--color-border` (Divider/Karten) bleibt unangetastet.
  - `--c-warning-600` (Light) `#8f6510 → #876010` — warning-Badge auf
    `warning-subtle` mit Puffer (vorher Kante 4.50).
- **Heading-Order / ARIA** (Admin-Views, von axe gefunden):
  - `app-card` hat jetzt einen `headingLevel`-Input (2|3|4, Default 3); Admin-Home-
    Kacheln nutzen `<h2>` (vorher h1→h3-Sprung).
  - Branding: Abschnitts-Überschrift `<h3>` → `<h2>` (Heading-Order).
  - Flow-Editor: Fehler-Alert war `<ul role="alert">` (unzulässige Rolle + kaputte
    Listen-Semantik) → `<div role="alert"><ul>…</ul></div>`.

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
- `a11y-admin-home.png`, `a11y-admin-users.png`, `a11y-admin-flow.png`,
  `a11y-admin-branding.png` — Admin-Views Light/Dark (neu im Scan, T-43 AC)
