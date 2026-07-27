---
name: loading-overlay-convention
description: global loading overlay = GET-only interceptor + SKIP_LOADING context token. Mutations, polls and typeahead never show it
metadata: 
  node_type: memory
  type: project
---

`loadingInterceptor` (`frontend/src/app/core/loading/loading.interceptor.ts`) drives the global loading overlay (`app-loading-overlay`, `LoadingService`). Convention since PR #9 (branch `fix/reduce-loading-spinners`, 2026-06-18): **the overlay only appears when loading data**.

Interceptor rule: it counts a request ONLY if `method === 'GET'` AND its `HttpContext` does not carry `SKIP_LOADING`. So:
- **Mutations** (POST/PUT/PATCH/DELETE) never show the overlay — rely on the local button `[loading]` or on optimistic updates.
- **Background GETs** (polls, post-mutation/WS refreshes, debounced typeahead) and **foreground loads that already render their own inline/pane spinner** opt out via `skipLoading()` (returns an `HttpContext` with `SKIP_LOADING=true`). One spinner per load — "local spinner wins" over the global overlay.
- A foreground GET with **no** local spinner keeps the overlay (its only indicator) — e.g. admin roles/users/webhooks/deadlines list pages.

How api methods expose it: default-quiet methods set `context: skipLoading()` unconditionally. A method called both foreground-overlay and background takes an `opts: { quiet?: boolean } = {}` and passes `context: opts.quiet ? skipLoading() : undefined`. The old `SKIP_LOADING_HEADER` was dead code (never set), so we removed it.

**How to apply:** for a new api-client/admin/budget/delegations GET method, decide per call site. If all callers are background or already show a local spinner, make the method default-quiet. If the callers are mixed, add the `quiet` opt and pass `{ quiet: true }` at the background, refresh and typeahead sites. Never add overlay logic to a mutation. Related: [[empty-state-convention]], [[ng-build-budgets]].
