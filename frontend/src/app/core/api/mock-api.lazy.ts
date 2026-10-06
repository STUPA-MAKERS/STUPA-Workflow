import type { HttpInterceptorFn } from '@angular/common/http';
import { EnvironmentInjector, inject, isDevMode, runInInjectionContext } from '@angular/core';
import { from, of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { USE_MOCK_API } from './api.config';

/**
 * The entry of the mock API in the interceptor chain of a dev or demo build. It loads
 * the mock (`mock-api.interceptor`, with its demo data) on the first request that the
 * mock answers, so the mock is not part of the initial bundle.
 *
 * It lets a request pass unchanged, without a load, when the build is not a dev build,
 * when the mock is off, or when the request does not go to the API. These are the first
 * checks of the mock itself, which stay as defense in depth.
 */
export const lazyMockApiInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isDevMode() || !inject(USE_MOCK_API) || !req.url.includes('/api/')) return next(req);
  const injector = inject(EnvironmentInjector);
  return from(import('./mock-api.interceptor')).pipe(
    // Dev only: a mock that does not load (for example a stale chunk after a rebuild)
    // does not break the app. The request goes on to the real backend.
    catchError((err: unknown) => {
      console.error('The mock API did not load; the request goes to the backend.', err);
      return of(null);
    }),
    switchMap((m) =>
      m ? runInInjectionContext(injector, () => m.mockApiInterceptor(req, next)) : next(req),
    ),
  );
};
