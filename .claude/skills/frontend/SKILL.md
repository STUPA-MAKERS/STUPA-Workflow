---
name: frontend
description: Angular 20 standalone SPA for STUPA-Workflow — apply wizard, meetings/live-vote/beamer, voting, budget/expenses/invoices, dashboard, tasks, account, and the whole admin config (forms/flow/gremien/roles/branding/mail-templates). Covers core (ApiClient, authGuard+authInterceptor, i18n DE/EN, theme, ws live-vote, loading overlay, branding, pwa), shared ui-kit + formly, lazy permission-gated routes, DESIGN_SYSTEM tokens. Use when working on any component, route, service, interceptor, UI-kit element, i18n string, theme/branding, or build in frontend/.
---

# Frontend — Angular 20 SPA — `frontend`

**Does:** The student-government platform's single-page app: public apply wizard + status timeline, role-aware dashboard, full screens for applications, voting (live-vote/beamer/cast), meetings (agenda/attendance/protocol), budget/expenses/invoices, account, and the admin config surface. Standalone components, signals, lazy permission-gated routes, typed API client over `/api`.

**Key files:**
- `src/app/app.config.ts` — composition root: interceptor chain `[loading, auth, mock?]` (mock added only in `isDevMode()`), `provideFormly`, `provideAppInitializer` (theme/i18n/branding/auth/sw), service worker (prod only), `LIVE_VOTE_SOURCE` factory.
- `src/app/app.routes.ts` — all routes under `ShellComponent`; lazy `loadComponent`, `canActivate: [authGuard]`, `data.permission` + flags (`allowAuthenticated`, `allowCommitteeMember`, `allowScopedBudgetView`, `wide`, `parent`, `title`).
- `src/app/core/api/api-client.service.ts` — typed HTTP facade (`ApiClient`) returning `Observable<…>`; one method per backend route.
- `src/app/core/api/api.config.ts` — `API_BASE_URL` token (`/api`), `USE_MOCK_API` token (default false; opt-in via `?mock=1`, `localStorage['useMockApi']`, `window.__USE_MOCK_API__`).
- `src/app/core/api/models.ts` — all DTO interfaces + `*Wire` raw shapes; `mappers.ts` converts wire→domain. `delegations.service.ts` = delegation API.
- `src/app/core/api/mock-api.interceptor.ts` — in-memory backend for dev/tests only.
- `src/app/core/auth/{auth.service,auth.guard,auth.interceptor}.ts` — `AuthService.can()/canAny()`, OIDC login/logout, session cookie/magic-link; guard reads `route.data.permission`, redirects to `/forbidden`; interceptor adds credentials + handles 401.
- `src/app/core/i18n/{i18n.service,translations,translate.pipe,localized-date.pipe}.ts` — DE/EN catalog, signal locale (stored→browser→DE fallback), `translate(key, params)`, `t`/`localizedDate` pipes.
- `src/app/core/theme/theme.service.ts` — `ThemePreference` light/dark/system; sets `data-theme` on `<html>`, follows OS via matchMedia, persisted.
- `src/app/core/branding/branding.service.ts` — `appName` from site-config else i18n `app.title`; sets `document.title`.
- `src/app/core/loading/{loading.service,loading.interceptor}.ts` — global overlay counter; opt out per-request via `SKIP_LOADING_HEADER` (`X-Skip-Loading`).
- `src/app/core/ws/{ws.service,live-vote.service,live-vote.source,mock-live-vote.source,ws-messages}.ts` — `/api/ws/meetings/{id}` (+`/beamer` read-only) live-vote channel; `LIVE_VOTE_SOURCE` swaps mock vs real.
- `src/app/core/pwa/sw-update.service.ts` — service-worker update prompt.
- `src/app/shared/ui/index.ts` — UI-kit barrel (Button/Input/Select/Checkbox/Datepicker/Table/DataTable/Card/Badge/Stepper/Dialog/Toast/Icon/CurrencyInput/Filter/ConfigDiff/LoadingOverlay). `ToastService` for toasts.
- `src/app/shared/ui/markdown-editor/` — Tiptap editor; **import directly, NOT via barrel** (keeps Tiptap in lazy chunk).
- `src/app/shared/formly/{formly.providers,formly-input.type}.ts` — ngx-formly bound to UI-kit; single `input` type covers text/number/currency/date. `shared/forms/{formly-mapper,jsonlogic,i18n-text}.ts` map backend form schema + JSONLogic guards.
- `src/app/shared/budget-path.ts` — `simplifyPathKey` / `SimplifyPathPipe` for cost-centre paths.
- `src/app/layout/{shell.component,breadcrumbs.component}.ts` — app shell (header/nav/theme/lang/footer/toasts); breadcrumbs from `route.data.parent`+`title`.
- `src/styles/tokens.scss`, `DESIGN_SYSTEM.md` — CD tokens (British Racing Green), Archivo font.

**Domain / data model:** DTOs in `core/api/models.ts`. `Principal` (id, permissions, gremien). Applications: `Application`/`ApplicationListItem`/`ApplicationType`, `EffectiveForm` (sections + `FormFieldDef`, `FieldType`), `Transition`/`TransitionResult`, `ApplicationVersion`/`DataDiff`, `ApplicationComment` (`CommentVisibility` internal/public), `Attachment` (`ScanState` scanning/clean/quarantined), `TimelineEntry`. Voting: `Vote`/`VoteConfig`/`Tally`/`Quorum`, `MajorityRule` simple/absolute/two_thirds, `VoteStatus` draft/open/closed/cancelled, `VoteResult` passed/rejected/tie, `BallotResult`. Meetings: `Meeting` (`MeetingStatus` planned/live/closed), `AgendaItem`, `Attendance` (`AttendanceStatus` present/excused/absent), `MeetingMember`, `MeetingVoteStatus` pending/open/closed/cancelled, `Protocol`. Plus `PublicSiteConfig`, `CalendarFeed`, `OAuthGrant`/`ConsentRequest`/`McpSetup`, `NotificationPreference`, `ProblemDetail` (RFC-9457). `Uuid`/`IsoDateTime` are string aliases.

**API surface (client → backend):** `ApiClient` methods map to `METHOD /api/...`:
- Identity/account: `me`, `logout`, `verifyMagicLink`, `myCalendar`/`rotateCalendar`, grants (`listGrants`/`revokeGrant`/`consentRequest`/`submitConsent`), `mcpConfig`/`downloadMcpPackage`, notification prefs.
- Applications: `applicationTypes`, `effectiveForm`, `listApplications`/`listTasks`, `getApplication`, `createApplication`/`updateApplication`/`deleteApplication`, `requestErasure`, `timeline`/`versions`/`comments`/`addComment`, `transitions`/`fireTransition` (+ `applicantTransitions`/`fireApplicantTransition`), attachments (`uploadAttachment`/`listAttachments`/`attachmentUrl`/`deleteAttachment`), `exportApplicationsXlsx`, `altchaChallenge`.
- Voting: `getVote`, `castBallot(id, choice, asDelegation)`, `openVote`/`closeVote`/`cancelVote`.
- Meetings: `createMeeting`/`getMeeting`/`patchMeeting`/`deleteMeeting`, `listMeetings`/`listMeetingsTimeline`/`listMeetingFilterGremien`/`listMeetingMembers`, attendance (`listAttendance`/`setOwnAttendance`/`setMemberAttendance`), agenda (`listAgenda`/`addAgendaItem`/`addAgendaFreetext`/`removeAgendaItem`/`setAgendaBody`/`renameAgendaItem`/`setAgendaNonPublic`/`reorderAgenda`/`listAssignableApplications`), votes (`openMeetingVote`/`deleteMeetingVote`), protocol (`loadProtocol`/`getProtocol`/`updateProtocol`/`embedVotes`/`finalizeProtocol`), `publicSiteConfig`.

**Conventions & gotchas:**
- Standalone components, `OnPush`, signals; **separate `.html`/`.scss` files** (no inline templates). Components use **only Semantic tokens** (`--color-*`), never Primitives (`--c-*`); add a primitive then map per-theme. Theme via `data-theme` on `<html>`.
- Routes are lazy + permission-gated: set `data.permission` (string or array → OR), plus `allowCommitteeMember`/`allowScopedBudgetView`/`allowAuthenticated` to widen. Missing permission → `/forbidden`. RBAC is also enforced server-side — the guard is UX only.
- Never show raw UUIDs in UI — resolve to names server-side ([[no-uuids-in-ui]]). Use the global `.empty-state` utility for empty tables/lists ([[empty-state-convention]]).
- Loading overlay is **GET-driven**; mutations/polls/typeahead opt out via `X-Skip-Loading` header / `skipLoading()` ([[loading-overlay-convention]]). Toasts via `ToastService`.
- All errors come back as `application/problem+json` (`ProblemDetail`); surface via toast.
- Mock interceptor is registered **only in dev builds** (`isDevMode()`); prod talks real `/api`. WS goes through nginx/`proxy.conf.json` in dev.
- **Bundle budgets:** run `npm run build` after component CSS/template changes — jest+tsc miss the per-component style budget that fails the Docker/prod build ([[ng-build-budgets]]). Import `MarkdownEditorComponent` by path, not the ui barrel.
- Edit i18n in BOTH `de` and `en` catalogs in `core/i18n/translations.ts`. Configurable DB texts (`*_i18n`) are NOT in I18nService.
- Commands: `npm start` (dev :4200), `npm run build` (→ `dist/antragsplattform/browser`), `npm test` (jest), `npm run test:cov` (FE coverage gate), `npm run lint`, `npm run typecheck`, `npm run e2e` (playwright).

**Related:** be-applications, be-flow, be-voting, be-livevote, be-budget, be-auth, be-admin, conventions
