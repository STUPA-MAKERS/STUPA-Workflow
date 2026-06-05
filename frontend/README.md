# Frontend — Antragsplattform SPA

Angular 20 (TS strict, standalone) SPA-Skelett + **Design-System** (T-03).
Routing-Gerüst, CD-Tokens (Light/Dark), self-hosted Web-Font, STUPA-Logo-Set,
`core/` (API-Client, WS-Service, Auth-Interceptor, i18n DE/EN), `shared/` UI-Kit
und Formly-Setup. Feature-Module folgen in T-30…T-36.

## Befehle

| Befehl | Zweck |
|---|---|
| `npm start` | Dev-Server (`http://localhost:4200`) |
| `npm run build` | Produktions-Build → `dist/antragsplattform` |
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
    pages/           Home, Platzhalter (Feature-Routen), 404
    app.config.ts    Composition Root (Provider, Interceptor-Kette, Init)
    app.routes.ts    Routing-Gerüst (Feature-Routen lazy → Platzhalter)
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
Im Skelett-Betrieb liefert `mockApiInterceptor` In-Memory-Antworten
(`USE_MOCK_API`, Default `true`), damit die SPA ohne Backend läuft. Für echte
Aufrufe `USE_MOCK_API` auf `false` setzen — `web`-nginx routet `/api` → `api`.

## Scope-Grenze (T-03)

Kein Feature-Code (Wizard, Voting, Admin …) — nur Gerüst, Design-System und
Infrastruktur. Backend (`backend/`) und `pytex/` bleiben unberührt (T-02/T-21).
