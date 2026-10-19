import { type HttpInterceptorFn, HttpContext, HttpContextToken } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs';
import { LoadingService } from './loading.service';

/**
 * Per-request opt-out for the global loading bar. `true` ⇒ this request does
 * not count toward the counter of the bar.
 */
export const SKIP_LOADING = new HttpContextToken<boolean>(() => false);

/** Reads started inside {@link quietly} right now. */
let quiet = 0;

/**
 * Start reads that do not count toward the bar, without a context on each call: a read
 * ahead runs the same service calls as the detail it warms, and those set no
 * `SKIP_LOADING`. The interceptor chain runs synchronously when a read is subscribed, so
 * a counter around `start` reaches every GET it subscribes.
 */
export function quietly<T>(start: () => T): T {
  quiet++;
  try {
    return start();
  } finally {
    quiet--;
  }
}

/** Ready-made {@link HttpContext} that suppresses the global loading bar. */
export function skipLoading(): HttpContext {
  return new HttpContext().set(SKIP_LOADING, true);
}

/**
 * Feeds the global loading bar through the {@link LoadingService}.
 *
 * The bar must appear only while the app loads data. Only GET requests
 * count. A request that opts out with {@link SKIP_LOADING} never counts.
 *
 * - Mutations (POST/PUT/PATCH/DELETE) never trigger the bar.
 *   They have local feedback (button `loading`, optimistic updates).
 *   They also must not flash the view (autosave, vote, reorder, finalize …).
 * - Background GETs skip the bar with `SKIP_LOADING`.
 *   Examples: status polls, a refresh after a mutation or a WS event, and a
 *   debounced typeahead.
 *   A load that already shows a local spinner also sets `SKIP_LOADING`.
 *   Two spinners then never stack.
 *
 * Register this as the outermost interceptor. It then measures the full request
 * duration, including the auth and mock layers.
 */
export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET' || quiet > 0 || req.context.get(SKIP_LOADING)) {
    return next(req);
  }
  const loading = inject(LoadingService);
  loading.inc();
  return next(req).pipe(finalize(() => loading.dec()));
};
