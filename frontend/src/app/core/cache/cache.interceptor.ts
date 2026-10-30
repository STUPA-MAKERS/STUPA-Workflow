import {
  HttpContext,
  HttpContextToken,
  type HttpEvent,
  type HttpInterceptorFn,
  HttpResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { type Observable, concat, filter, finalize, of, share, tap } from 'rxjs';
import { skipLoading } from '@stupa-makers/ui-kit';
import { HttpCacheService } from './http-cache.service';

/** How long a cached answer may be served before it is refetched. */
const DEFAULT_TTL_MS = 60_000;

/**
 * How old a stored list page may be and still be painted while it revalidates.
 *
 * Generous on purpose. A hit always issues the request too, so what the reader sees is
 * corrected within one round trip whatever this number is; it only decides whether the
 * first page appears at once or as a loading state. The cost of being wrong is a value
 * that changes under the reader a moment later, and the cost of being too strict is the
 * spinner on every page switch.
 */
export const LIST_TTL_MS = 120_000;

/**
 * How old a read-ahead detail may be and still be painted while it revalidates. Like
 * {@link LIST_TTL_MS}: a hit always reads again, so this only decides whether a clicked
 * row shows at once or as a loading state.
 */
export const DETAIL_TTL_MS = 120_000;

/** Per-request opt-in. `0` (the default) means "do not cache this". */
const CACHE_TTL = new HttpContextToken<number>(() => 0);

/**
 * Ready-made {@link HttpContext} that caches this GET and serves it again while it
 * revalidates.
 *
 * Opt IN per call site, never by default. A caller has to know two things this
 * interceptor cannot: whether a slightly old answer is acceptable, and whether the code
 * downstream can handle being called twice.
 *
 * It takes a base context, because the calls worth caching are exactly the background ones that
 * already carry `skipLoading()`, and a second `new HttpContext()` would throw the first away.
 */
export function cached(
  ttlMs: number = DEFAULT_TTL_MS,
  base: HttpContext = new HttpContext(),
): HttpContext {
  return base.set(CACHE_TTL, ttlMs);
}

/**
 * The request context for one page of a list.
 *
 * Page one is cached, so returning to a list paints it at once instead of showing a
 * loading state for a round trip. A LOAD-MORE page is not, and that is the whole reason
 * this decision lives in one function: a cached GET emits twice, and a second emission
 * on a load-more page would append the same rows again. Deciding per call site is how a
 * list ends up quietly duplicating its rows.
 */
export function listContext(offset: number | undefined): HttpContext {
  return offset ? skipLoading() : cached(LIST_TTL_MS, skipLoading());
}

/**
 * The request context for a read that the detail of a list row makes when it opens.
 *
 * The list reads it ahead for the rows it shows (`prefetchDetails`), so a click paints
 * the detail at once. Only for a read whose subscriber takes a second emission, because a
 * hit emits twice when the fresh answer differs. It skips the loading bar: the detail
 * shows its own loading state, and a hit that reads again behind the painted answer must
 * not run the bar over it.
 */
export function detailContext(base: HttpContext = skipLoading()): HttpContext {
  return cached(DETAIL_TTL_MS, base);
}

/** Reads started inside {@link freshly} right now. */
let freshReads = 0;

/**
 * Start reads that skip the stored answer and wait for the network: the reload of a pull
 * to refresh, where the person asked for the data of now. The answer still goes into the
 * cache, and no other entry is dropped, so the details that a list read ahead stay. Like
 * `quietly`, the counter reaches every GET that `start` subscribes synchronously.
 */
export function freshly<T>(start: () => T): T {
  freshReads++;
  try {
    return start();
  } finally {
    freshReads--;
  }
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
 *
 * Invalidation happens on the way out, not on the response: a request that fails may still have
 * changed something, and a stale list after a half-failed write is worse than one extra fetch. A
 * read ahead that is still in flight is joined, so a click right after the list appeared waits for
 * one answer, not two. The same answer again is no news, so an unchanged detail does not render
 * twice. The cached body comes first, then the network answer. `concat` keeps the order and does
 * not start the request until the cached value is delivered.
 */
export const cacheInterceptor: HttpInterceptorFn = (req, next) => {
  const cache = inject(HttpCacheService);

  if (req.method !== 'GET') {
    cache.invalidate(new URL(req.url, 'http://x').pathname);
    return next(req);
  }

  const ttl = req.context.get(CACHE_TTL);
  if (ttl <= 0) return next(req);

  const key = req.urlWithParams;
  const hit = freshReads > 0 ? undefined : cache.get(key, ttl);
  if (hit === undefined) {
    const flying = freshReads > 0 ? undefined : inflight.get(key);
    if (flying) return flying;
    const fresh = next(req).pipe(
      tap((event) => {
        if (event instanceof HttpResponse && event.status === 200) cache.set(key, event.body);
      }),
      finalize(() => inflight.delete(key)),
      share(),
    );
    inflight.set(key, fresh);
    return fresh;
  }

  const fresh = next(req).pipe(
    tap((event) => {
      if (event instanceof HttpResponse && event.status === 200) cache.set(key, event.body);
    }),
    filter((event) => !(event instanceof HttpResponse && sameBody(event.body, hit))),
  );

  return concat(of(new HttpResponse({ body: hit, status: 200 })), fresh);
};

/** The cached reads in flight by key, shared between the reader ahead and a click. */
const inflight = new Map<string, Observable<HttpEvent<unknown>>>();

function sameBody(a: unknown, b: unknown): boolean {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
