import { HttpErrorResponse, type HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import { APP_VERSION_HEADER, AppVersionService } from './app-version.service';

/**
 * Reports the header `X-App-Version` of each API answer, also of an error answer, to
 * {@link AppVersionService} (§ 002151). Requests to other hosts are not reported. It sits
 * inside the cache interceptor, so a cached answer with an old header does not count.
 */
export const appVersionInterceptor: HttpInterceptorFn = (req, next) => {
  const base = inject(API_BASE_URL);
  if (!req.url.startsWith(`${base}/`)) return next(req);
  const versions = inject(AppVersionService);
  return next(req).pipe(
    tap({
      next: (event) => {
        if (event instanceof HttpResponse) versions.report(event.headers.get(APP_VERSION_HEADER));
      },
      error: (err: unknown) => {
        if (err instanceof HttpErrorResponse) versions.report(err.headers.get(APP_VERSION_HEADER));
      },
    }),
  );
};
