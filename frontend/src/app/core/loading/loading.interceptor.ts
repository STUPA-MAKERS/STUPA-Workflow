import { type HttpInterceptorFn, HttpContext, HttpContextToken } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs';
import { LoadingService } from './loading.service';

/**
 * Per-request opt-out for the global loading overlay. `true` ⇒ this request does
 * not count toward the overlay counter.
 */
export const SKIP_LOADING = new HttpContextToken<boolean>(() => false);

/** Ready-made {@link HttpContext} that suppresses the global loading overlay. */
export function skipLoading(): HttpContext {
  return new HttpContext().set(SKIP_LOADING, true);
}

/**
 * Feeds the global loading overlay via the {@link LoadingService}.
 *
 * The overlay should only appear when data is being loaded — so only GET
 * requests count, and only while they are not opted out via {@link SKIP_LOADING}:
 *
 * - Mutations (POST/PUT/PATCH/DELETE) never trigger the overlay — they have
 *   local feedback (button `loading`, optimistic updates) and should not flash
 *   the view (autosave, vote, reorder, finalize …).
 * - Background GETs (status polls, refresh after a mutation/WS event, debounced
 *   typeahead) and loads that already show a local spinner set `SKIP_LOADING`
 *   and skip the overlay — so two spinners never stack.
 *
 * Registered as the outermost interceptor so the full request duration (incl.
 * auth/mock) is captured.
 */
export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET' || req.context.get(SKIP_LOADING)) {
    return next(req);
  }
  const loading = inject(LoadingService);
  loading.inc();
  return next(req).pipe(finalize(() => loading.dec()));
};
