import {
  HttpContext,
  HttpContextToken,
  type HttpInterceptorFn,
  HttpResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { concat, of, tap } from 'rxjs';
import { HttpCacheService } from './http-cache.service';

/** How long a cached answer may be served before it is refetched. */
const DEFAULT_TTL_MS = 60_000;

/** Per-request opt-in. `0` (the default) means "do not cache this". */
const CACHE_TTL = new HttpContextToken<number>(() => 0);

/**
 * Ready-made {@link HttpContext} that caches this GET and serves it again while it
 * revalidates.
 *
 * Opt IN per call site, never by default. A caller has to know two things this
 * interceptor cannot: whether a slightly old answer is acceptable, and whether the code
 * downstream can handle being called twice.
 */
export function cached(
  ttlMs: number = DEFAULT_TTL_MS,
  base: HttpContext = new HttpContext(),
): HttpContext {
  // Takes a base context, because the calls worth caching are exactly the background
  // ones that already carry `skipLoading()`, and a second `new HttpContext()` would
  // throw the first away.
  return base.set(CACHE_TTL, ttlMs);
}

/**
 * Serve-then-revalidate for reference data, and invalidate on every mutation.
 *
 * A cached GET emits **twice**: the stored answer at once, then the fresh one when it
 * arrives. That is the whole point — a page paints immediately and corrects itself — but
 * it is also why this is opt-in. A caller that takes only the first emission
 * (`firstValueFrom`, a one-shot `subscribe` that then unsubscribes) would silently keep
 * the old answer, so a call site has to choose this knowingly.
 *
 * A non-GET drops every cached entry under the same collection path, so a booking that
 * was just created cannot be missing from the list that follows it.
 */
export const cacheInterceptor: HttpInterceptorFn = (req, next) => {
  const cache = inject(HttpCacheService);

  if (req.method !== 'GET') {
    // Invalidate on the way OUT, not on the response: a request that fails may still
    // have changed something, and serving a stale list after a half-failed write is
    // worse than one extra fetch.
    cache.invalidate(new URL(req.url, 'http://x').pathname);
    return next(req);
  }

  const ttl = req.context.get(CACHE_TTL);
  if (ttl <= 0) return next(req);

  const key = req.urlWithParams;
  const fresh = next(req).pipe(
    tap((event) => {
      if (event instanceof HttpResponse && event.status === 200) cache.set(key, event.body);
    }),
  );

  const hit = cache.get(key, ttl);
  if (hit === undefined) return fresh;

  // The cached body first, then the network answer. `concat` keeps the order and does not
  // start the request until the cached value is delivered, so the subscriber always sees
  // something to paint before anything else happens.
  return concat(of(new HttpResponse({ body: hit, status: 200 })), fresh);
};
