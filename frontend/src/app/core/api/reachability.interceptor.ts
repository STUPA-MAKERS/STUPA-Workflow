import { HttpErrorResponse, type HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';
import { API_BASE_URL } from './api.config';
import { ServerReachabilityService, isUnreachableStatus } from './server-reachability.service';

/**
 * Reports each API answer to {@link ServerReachabilityService} (§ 000578): an error with no
 * status, 502, 503 or 504 may mean that the server is not there, every other answer (also a
 * 4xx or a 500) means that it is. Requests to other hosts are not reported. It sits inside the
 * cache interceptor, so a cached answer does not count.
 */
export const reachabilityInterceptor: HttpInterceptorFn = (req, next) => {
  const base = inject(API_BASE_URL);
  if (!req.url.startsWith(`${base}/`)) return next(req);
  const reach = inject(ServerReachabilityService);
  return next(req).pipe(
    tap({
      next: (event) => {
        if (event instanceof HttpResponse) reach.reportSuccess();
      },
      error: (err: unknown) => {
        if (!(err instanceof HttpErrorResponse)) return;
        if (isUnreachableStatus(err.status)) reach.reportFailure(err.status);
        else reach.reportSuccess();
      },
    }),
  );
};
