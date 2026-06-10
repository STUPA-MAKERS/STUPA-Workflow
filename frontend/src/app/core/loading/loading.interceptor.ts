import { type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs';
import { LoadingService } from './loading.service';

/** Requests, die den Ladebildschirm NICHT auslösen sollen, setzen diesen Header. */
export const SKIP_LOADING_HEADER = 'X-Skip-Loading';

/**
 * Zählt laufende Requests im {@link LoadingService} → globaler Ladebildschirm
 * (#loading). Als **äußerster** Interceptor registriert, damit die volle Request-
 * Dauer (inkl. Auth/Mock) erfasst wird. Hintergrund-Polling kann sich per
 * {@link SKIP_LOADING_HEADER} ausklinken (Header wird vor dem Senden entfernt).
 */
export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.headers.has(SKIP_LOADING_HEADER)) {
    return next(req.clone({ headers: req.headers.delete(SKIP_LOADING_HEADER) }));
  }
  const loading = inject(LoadingService);
  loading.inc();
  return next(req).pipe(finalize(() => loading.dec()));
};
