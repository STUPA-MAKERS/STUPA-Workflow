# Frontend — STUPA-Workflow SPA

Angular (TS strict, standalone components mit **separaten `.html`/`.scss`-Dateien**).
Design-System (CD-Tokens, Dark-Mode, Web-Font, STUPA-Logos), `core/` (typisierter
API-Client, Auth-Interceptor, i18n DE/EN, Theme, WS-Service), `shared/` UI-Kit +
Formly-Bindung.

Gebaut: der öffentliche **Apply-Wizard** (mehrstufig, Altcha, Draft-Persistenz),
**Status-Timeline** und **Confirmation**, das rollenabhängige **Dashboard** sowie die
Voll-Screens für **Applications**, **Voting**, **Meetings** (inkl. Live-Vote/Beamer),
**Budget/Expenses/Invoices** und die **Admin-Konfiguration** (Forms, Flow, Gremien,
Rollen, Branding, Mail-Templates, …). Feature-Routen sind lazy + permission-gegatet.

## Befehle

| Befehl | Zweck |
|---|---|
| `npm start` | Dev-Server (`http://localhost:4200`) |
| `npm run build` | Produktions-Build → `dist/antragsplattform/browser` |
| `npm test` | Jest (jsdom + Angular Testing Library) |
| `npm run test:cov` | Jest mit Coverage-Gate (FE ≥80 %) |
| `npm run lint` | ESLint (flat config, `@angular-eslint`) |
| `npm run typecheck` | `tsc --strict --noEmit` |

> Node ≥ 24.x. `npm install` lädt Angular 20 + Toolchain. Kein `sudo` nötig.

## Projektstruktur

```
src/
  styles/            Design-System (Tokens, Fonts, Base) — siehe DESIGN_SYSTEM.md
  assets/fonts/      Archivo (OFL, self-hosted woff2) — Web-Ersatz für DIN
  assets/logos/      Offizielle STUPA-CD-Logos (Marke + Wortmarke)
  app/
    core/            App-weite Singletons (kein UI)
      api/           Typisierter API-Client + DTOs + Mock-Interceptor
      auth/          AuthService + Auth-Interceptor (Session-Cookie / Magic-Link)
      ws/            Live-Vote WebSocket-Service (RxJS)
      i18n/          I18nService (DE/EN, Fallback DE) + `t`-Pipe
      theme/         ThemeService (System + Toggle, persistiert)
    shared/
      ui/            UI-Kit: Button/Input/Card/Table/Stepper/Dialog/Toast/Badge
      formly/        Formly-Bindung an das UI-Kit (Feldtyp `input`)
    layout/          ShellComponent (Header/Nav/Theme/Sprache/Footer/Toasts)
    pages/           Home, Dashboard, Applications, Voting, Budget/Expenses/Invoices,
                     Tasks, Account, Admin (Forms/Flow/Gremien/Rollen/…), 404
    features/        apply/ (Wizard, Confirmation, Timeline, Altcha), meetings/,
                     voting/ (Live-Vote, Beamer)
    app.config.ts    Composition Root (Provider, Interceptor-Kette, Init)
    app.routes.ts    Routing (Feature-Routen lazy, permission-gegatet)
```

## Design-System

CD-Tokens als CSS-Custom-Properties aus der STUPA-Palette (`britishracinggreen`
primär), zweistufig (Primitive → Semantic). **Light + Dark** über
`data-theme` auf `<html>`; `ThemeService` folgt dem OS und erlaubt einen
persistierten Toggle. Vollständige Token-Referenz: **[DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)**.

- **Web-Font:** Archivo (freie Grotesk, DIN-ähnlich, OFL), self-hosted unter
  `assets/fonts`. Austauschbar über das Token `--font-sans`. **DIN bleibt
  PDF-only** (requirements N1, Q15b) — kein DIN-Web-Font.
- **Logos:** Offizielle STUPA-CD-Assets aus Nextcloud (Marke + Wortmarke);
  STUPA-only, kein Hochschul-Logo. Wortmarke fixes `#706f6f` (gray-text), kein
  `currentColor` (Einbindung per `<img src>`). Details: `assets/logos/README.md`.

## i18n

UI-Strings DE/EN (`core/i18n`). Locale aus persistierter Wahl → Browser → DE.
Fehlende Keys fallen auf DE zurück. Umschaltung über den Sprach-Switcher im
Header. Konfigurierbare DB-Texte (`*_i18n`) sind **nicht** Teil dieses Service.

## API-Client & Mock

`core/api/ApiClient` ist gegen die OpenAPI-Contracts (`sds/api.md`) typisiert.
`mockApiInterceptor` liefert In-Memory-Antworten. Default ist **`USE_MOCK_API=false`**
(#67): die SPA spricht das **echte** Backend (`/api`) an — `web`-nginx routet `/api`
→ `api`; im Dev leitet `proxy.conf.json` (`ng serve`) `/api` inkl. WebSocket weiter.
Der Mock ist nur noch ein **explizites** Opt-in für Dev/Tests: `?mock=1`,
`localStorage['useMockApi']='1'` oder `window.__USE_MOCK_API__=true` vor dem Bootstrap.

> Der WS-Service (`core/ws`) verbindet `ws(s)://…/api/ws/meetings/{id}` (Live-Vote);
> der Server-Endpoint existiert (T-16) und wird hinter nginx/`proxy.conf.json`
> durchgereicht.
