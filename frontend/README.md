# Frontend — STUPA-Workflow SPA

Angular with strict TypeScript. Standalone components keep **separate `.html` and `.scss`
files**. The design system holds the CD tokens, dark mode, the web font and the STUPA logos.
`core/` holds the typed API client, the auth interceptor, i18n for German and English, the theme
and the WebSocket service. `shared/` holds the UI kit and the Formly binding.

These parts are built. The public **apply wizard** runs in several steps with ALTCHA and draft
persistence. It comes with the **status timeline** and the **confirmation** page. The
**start page** shows one work list (open tasks, own applications, votes) and a side sheet for
today. List/detail pane pages exist for **applications**, **tasks**, **votes**, **meetings**
(list or calendar, with live vote, beamer and the Kalender-Abo popover), **bookings** and
**invoices**. The **budget** page shows the cost-centre tree. The **account** area and the **admin
configuration** (forms, flow, Gremien, roles, branding, mail templates and more) share one
2-pane frame. Guests of a
public meeting join through `/j/:code`.
Feature routes load lazily and a permission gate protects them.

## Commands

| Command | Purpose |
|---|---|
| `npm start` | Dev server (`http://localhost:4200`) |
| `npm run build` | Production build → `dist/antragsplattform/browser` |
| `npm test` | Jest (jsdom and Angular Testing Library) |
| `npm run test:cov` | Jest with the coverage gate (statements 98 %, branches 96 %, functions 98 %, lines 99 %) |
| `npm run lint` | ESLint (flat config, `@angular-eslint`) |
| `npm run typecheck` | `tsc -p tsconfig.app.json --noEmit` (strict) |

> Node 22 or newer. `npm install` fetches Angular 20 and the toolchain. You do not need `sudo`.

## Project structure

```
src/
  styles.scss        Global styles: loads the ui-kit fonts, tokens and base, adds app utilities
  assets/logos/      Official STUPA CD logos (mark + word mark)
  app/
    core/            App-wide singletons (no UI)
      api/           Typed API client + DTOs + mock interceptor
      auth/          AuthService + auth interceptor (session cookie / magic link)
      ws/            Live-vote WebSocket service (RxJS)
      i18n/          I18nService (DE/EN, fallback DE) + `t` pipe
      theme/         ThemeService (system + toggle, persisted)
    shared/
      ui/            App building blocks (empty state, page header, skeleton)
      formly/        Formly binding to the UI kit (field type `input`)
    layout/          ShellComponent (frame), nav rail, phone bottom bar, account menu,
                     public top bar, branded footer, rail marks
    pages/           Home, Dashboard, Applications, Budget/Expenses/Invoices, Tasks,
                     Account, Admin (Forms/Flow/Gremien/Roles/…), 403, 404, error page
    features/        apply/ (Wizard, Confirmation, Timeline, Altcha), meetings/,
                     voting/ (live vote, beamer), public-meeting/ (guest join `/j/:code`),
                     search/ (search palette)
    app.config.ts    Composition root (providers, interceptor chain, init)
    app.routes.ts    Routing (feature routes lazy, permission-gated)
vendor/ui-kit/       Submodule STUPA-MAKERS/ui-kit: tokens, fonts, breakpoints, components
```

## Design system

The design system has one accent colour (green `#72a384`), neutral grey surfaces and two
signal colours. The ui-kit submodule (`vendor/ui-kit`) holds the tokens, the fonts, the
breakpoints and the components. The tokens have two levels: primitive and semantic. The
`data-theme` attribute on `<html>` selects **light** or **dark**. `ThemeService` follows the
operating system and remembers a manual toggle. It also sets the `theme-color` meta tags to
the page background of the theme, so the browser and PWA bars follow the theme. For the
tokens, the breakpoints and the binding UI rules, see **[DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)**.

- **Web fonts:** IBM Plex Sans (400/500/600/700) and IBM Plex Mono (400/500), under the SIL
  Open Font License. The kit ships the `woff2` files in `vendor/ui-kit/src/assets/fonts`, and
  `angular.json` copies them to `/assets/fonts`. The CSP allows only fonts from the own
  origin, so do not load fonts from a CDN. Change the tokens `--font-sans` and `--font-mono`
  to use another face. **DIN stays PDF only** (requirements N1, Q15b). There is no DIN web
  font.
- **Icons:** `app-icon` draws line icons as inline SVG. The app loads no icon font.
- **Logos:** The official STUPA CD assets come from Nextcloud and hold the mark and the word
  mark. Use STUPA logos only. Do not use the logo of the university. The word mark has a light
  variant (black text) and a dark variant (white text). The public top bar
  (`PublicHeaderComponent`) picks the variant from the active theme; the navigation rail shows
  the mark alone. Neither variant follows `currentColor`, because the page embeds it through
  `<img src>`. For details, see `assets/logos/README.md`.

## i18n

The UI strings exist in German and English (`core/i18n`). The service takes the locale from the
stored choice, then from the browser, then from the German default. A missing key falls back to
German. The account menu (and, while nobody is signed in, the public top bar) changes the
locale. Configurable database texts
(`*_i18n`) are **not** part of this service.

## API client and mock

`core/api/ApiClient` follows the types of the backend Pydantic schemas (camelCase wire keys).
`mockApiInterceptor` returns in-memory answers. The default is **`USE_MOCK_API=false`** (#67).
The SPA talks to the **real** backend under `/api`. The `web` nginx routes `/api` to `api`. In
development, `proxy.conf.json` (`ng serve`) forwards `/api` and the WebSocket. The mock is now
an **explicit** opt-in for development and tests. Turn it on with `?mock=1`, with
`localStorage['useMockApi']='1'` or with `window.__USE_MOCK_API__=true` before the bootstrap.

> The WebSocket service (`core/ws`) connects to `ws(s)://…/api/ws/meetings/{id}` for the live
> vote. The server endpoint exists (T-16). nginx and `proxy.conf.json` pass it through.
