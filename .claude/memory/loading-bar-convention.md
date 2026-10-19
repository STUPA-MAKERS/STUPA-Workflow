---
name: loading-bar-convention
description: The global loading bar counts GETs only. Background reads opt out with skipLoading() or quietly(); mutations never count
metadata:
  node_type: memory
  type: project
---

The global loading bar (`layout/load-bar`, a 3px line at the top) shows while the app loads
data. `LoadingService` (`frontend/src/app/core/loading/loading.service.ts`) counts the open
requests. The bar appears after 300 ms and stays at least 400 ms, so a fast answer shows
nothing.

`loadingInterceptor` (`core/loading/loading.interceptor.ts`) counts a request only if it is a
GET, it does not carry the `SKIP_LOADING` context token, and it does not start inside
`quietly(() => …)`.

- **Mutations** (POST/PUT/PATCH/DELETE) never count. They use local feedback: the button
  `[loading]` or an optimistic update.
- **Background GETs** opt out with `context: skipLoading()`: polls, a refresh after a mutation
  or a WS event, a debounced typeahead.
- **A load with its own local spinner or skeleton** also opts out, so two indicators never
  stack.
- **A read-ahead** that calls the normal service methods wraps them in `quietly()`
  (`core/cache/detail-prefetch.ts`), because those methods set no context.
- A foreground GET with no local indicator keeps the bar, because the bar is its only signal.

**How to apply:** decide per call site when you add an API GET method. If every caller is
background or shows its own spinner, make the method quiet by default (`context:
skipLoading()`). If the callers are mixed, add `opts: { quiet?: boolean } = {}`, pass
`context: opts.quiet ? skipLoading() : undefined`, and pass `{ quiet: true }` at the
background, refresh and typeahead sites. Never add loading logic to a mutation.
Related: [[empty-state-convention]].
