---
name: loading-overlay-convention
description: global loading overlay = GET-only interceptor + SKIP_LOADING context token; mutations/polls/typeahead never show it
metadata: 
  node_type: memory
  type: project
---

Global loading overlay (`app-loading-overlay`, `LoadingService`) is driven by `loadingInterceptor` (`frontend/src/app/core/loading/loading.interceptor.ts`). Convention since PR #9 (branch `fix/reduce-loading-spinners`, 2026-06-18): **the overlay only appears when loading data**.

Interceptor rule: counts a request ONLY if `method === 'GET'` AND its `HttpContext` does not carry `SKIP_LOADING`. So:
- **Mutations** (POST/PUT/PATCH/DELETE) never show the overlay — rely on local button `[loading]` / optimistic updates.
- **Background GETs** (polls, post-mutation/WS refreshes, debounced typeahead) and **foreground loads that already render their own inline/pane spinner** opt out via `skipLoading()` (returns an `HttpContext` with `SKIP_LOADING=true`). One spinner per load — "local spinner wins" over the global overlay.
- A foreground GET with **no** local spinner keeps the overlay (its only indicator) — e.g. admin roles/users/webhooks/deadlines list pages.

How api methods expose it: default-quiet methods set `context: skipLoading()` unconditionally; methods called both foreground-overlay and background take an `opts: { quiet?: boolean } = {}` and pass `context: opts.quiet ? skipLoading() : undefined`. The old `SKIP_LOADING_HEADER` was dead code (never set) and was removed.

**How to apply:** new api-client/admin/budget/delegations GET methods — decide per call site: if all callers are background or already show a local spinner, default-quiet it; if mixed, add the `quiet` opt and pass `{ quiet: true }` at background/refresh/typeahead sites. Never add overlay logic to mutations. Related: [[empty-state-convention]], [[ng-build-budgets]].
