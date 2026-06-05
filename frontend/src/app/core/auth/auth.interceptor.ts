import { type HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { AuthService } from './auth.service';

/** Double-Submit-CSRF: Cookie (lesbar) → gespiegelt im Header (security.md §10). */
const CSRF_COOKIE = 'XSRF-TOKEN';
const CSRF_HEADER = 'X-XSRF-TOKEN';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** Endpunkte, deren 401 erwartbar/anonym ist → kein erzwungener Re-Login. */
function isAnonymousAuthProbe(url: string): boolean {
  return url.includes('/auth/me') || url.includes('/auth/login');
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Hängt Auth an ausgehende `/api`-Requests:
 * - `withCredentials` → HttpOnly-Session-Cookie (OIDC-Principal, api.md §1).
 * - Magic-Link-Applicant-Token als `Authorization: Bearer` (falls vorhanden).
 * - **CSRF**: bei schreibenden Methoden das `XSRF-TOKEN`-Cookie als Header
 *   spiegeln (Double-Submit, security.md §10) — same-origin `/api` only.
 * - **401**: abgelaufene/fehlende Session → Principal verwerfen + Re-Login
 *   (außer beim anonymen `/auth/me`-Probe beim App-Start).
 * Keine Tokens an Fremd-Hosts.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.includes('/api/')) return next(req);

  const auth = inject(AuthService);
  const applicantToken = auth.applicantToken();
  const csrfToken = UNSAFE_METHODS.has(req.method) ? readCookie(CSRF_COOKIE) : null;

  const setHeaders: Record<string, string> = {};
  if (applicantToken) setHeaders['Authorization'] = `Bearer ${applicantToken}`;
  if (csrfToken) setHeaders[CSRF_HEADER] = csrfToken;

  const authed = req.clone({ withCredentials: true, setHeaders });

  return next(authed).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !isAnonymousAuthProbe(req.url)) {
        auth.handleUnauthorized();
      }
      return throwError(() => err);
    }),
  );
};
