# Frontend — STUPA-Workflow SPA

Angular with strict TypeScript. Standalone components keep **separate `.html` and `.scss`
files**. The design system holds the CD tokens, dark mode, the web font and the STUPA logos.
`core/` holds the typed API client, the auth interceptor, i18n for German and English, the theme
and the WebSocket service. `shared/` holds the UI kit and the Formly binding.

These parts are built. The public **apply wizard** runs in several steps with ALTCHA and draft
persistence. It comes with the **status timeline** and the **confirmation** page. The
**dashboard** adapts to the role of the user. Full screens exist for **applications**,
**voting**, **meetings** (with live vote and beamer) and **budget, expenses and invoices**. The
**admin configuration** covers forms, flow, Gremien, roles, branding, mail templates and more.
Feature routes load lazily and a permission gate protects them.

## Commands

| Command | Purpose |
|---|---|
| `npm start` | Dev server (`http://localhost:4200`) |
| `npm run build` | Production build → `dist/antragsplattform/browser` |
| `npm test` | Jest (jsdom and Angular Testing Library) |
| `npm run test:cov` | Jest with the coverage gate (frontend ≥ 80 %) |
| `npm run lint` | ESLint (flat config, `@angular-eslint`) |
| `npm run typecheck` | `tsc --strict --noEmit` |

> Node ≥ 24.x. `npm install` fetches Angular 20 and the toolchain. You do not need `sudo`.

## Project structure

```
src/
  styles/            Design system (tokens, fonts, base) — see DESIGN_SYSTEM.md
  assets/fonts/      Archivo (OFL, self-hosted woff2) — web substitute for DIN
  assets/logos/      Official STUPA CD logos (mark + word mark)
  app/
    core/            App-wide singletons (no UI)
      api/           Typed API client + DTOs + mock interceptor
      auth/          AuthService + auth interceptor (session cookie / magic link)
      ws/            Live-vote WebSocket service (RxJS)
      i18n/          I18nService (DE/EN, fallback DE) + `t` pipe
      theme/         ThemeService (system + toggle, persisted)
    shared/
      ui/            UI kit: Button/Input/Card/Table/Stepper/Dialog/Toast/Badge
      formly/        Formly binding to the UI kit (field type `input`)
    layout/          ShellComponent (Header/Nav/Theme/Language/Footer/Toasts)
    pages/           Home, Dashboard, Applications, Voting, Budget/Expenses/Invoices,
                     Tasks, Account, Admin (Forms/Flow/Gremien/Roles/…), 404
    features/        apply/ (Wizard, Confirmation, Timeline, Altcha), meetings/,
                     voting/ (live vote, beamer)
    app.config.ts    Composition root (providers, interceptor chain, init)
    app.routes.ts    Routing (feature routes lazy, permission-gated)
```

## Design system

The CD tokens are CSS custom properties from the STUPA palette. `britishracinggreen` is the
primary color. The tokens have two levels: primitive and semantic. The `data-theme` attribute
on `<html>` selects **light** or **dark**. `ThemeService` follows the operating system and
remembers a manual toggle. For the full token reference, see
**[DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)**.

- **Web font:** Archivo, a free grotesque face close to DIN, under the OFL license. The app
  hosts it in `assets/fonts`. Change the token `--font-sans` to use another face. **DIN stays
  PDF only** (requirements N1, Q15b). There is no DIN web font.
- **Logos:** The official STUPA CD assets come from Nextcloud and hold the mark and the word
  mark. Use STUPA logos only. Do not use the logo of the university. The word mark has the
  fixed color `#706f6f` (gray text) and does not follow `currentColor`, because the page
  embeds it through `<img src>`. For details, see `assets/logos/README.md`.

## i18n

The UI strings exist in German and English (`core/i18n`). The service takes the locale from the
stored choice, then from the browser, then from the German default. A missing key falls back to
German. The language switcher in the header changes the locale. Configurable database texts
(`*_i18n`) are **not** part of this service.

## API client and mock

`core/api/ApiClient` follows the types of the OpenAPI contracts (`sds/api.md`).
`mockApiInterceptor` returns in-memory answers. The default is **`USE_MOCK_API=false`** (#67).
The SPA talks to the **real** backend under `/api`. The `web` nginx routes `/api` to `api`. In
development, `proxy.conf.json` (`ng serve`) forwards `/api` and the WebSocket. The mock is now
an **explicit** opt-in for development and tests. Turn it on with `?mock=1`, with
`localStorage['useMockApi']='1'` or with `window.__USE_MOCK_API__=true` before the bootstrap.

> The WebSocket service (`core/ws`) connects to `ws(s)://…/api/ws/meetings/{id}` for the live
> vote. The server endpoint exists (T-16). nginx and `proxy.conf.json` pass it through.
