import { type HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { LOCATION } from '../browser/location.token';
import { AuthService } from './auth.service';

/** Double-submit CSRF: cookie (readable) → mirrored in the header. */
const CSRF_COOKIE = 'XSRF-TOKEN';
const CSRF_HEADER = 'X-XSRF-TOKEN';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Same-origin `/api`? Only then attach the session cookie + CSRF header —
 * otherwise credentials would leak to foreign hosts. Relative URLs (`/api/...`)
 * are same-origin by definition; absolute URLs must exactly match the browser
 * origin.
 */
function isSameOriginApi(url: string, origin: string): boolean {
  if (url.startsWith('/api/')) return true;
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url);
      return parsed.origin === origin && parsed.pathname.startsWith('/api/');
    } catch {
      return false;
    }
  }
  return false;
}

/** Endpoints whose 401 is expected → no forced re-login (loop/race). */
function skipReloginOn(url: string): boolean {
  return url.includes('/auth/me') || url.includes('/auth/login') || url.includes('/auth/logout');
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Attaches auth to outgoing same-origin `/api` requests:
 * - `withCredentials` → HttpOnly cookies (OIDC principal / magic-link
 *   applicant). No token in JS storage; nothing exfiltrable via XSS.
 * - CSRF: on writing methods, mirror the `XSRF-TOKEN` cookie into a header
 *   (double-submit).
 * - 401: expired/missing session → drop the principal + re-login (except on the
 *   auth endpoints, whose 401 is expected).
 * Foreign origins are left untouched — no credentials/headers leave.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isSameOriginApi(req.url, inject(LOCATION).origin)) return next(req);

  const auth = inject(AuthService);
  const csrfToken = UNSAFE_METHODS.has(req.method) ? readCookie(CSRF_COOKIE) : null;

  const setHeaders: Record<string, string> = {};
  if (csrfToken) setHeaders[CSRF_HEADER] = csrfToken;

  const authed = req.clone({ withCredentials: true, setHeaders });

  return next(authed).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !skipReloginOn(req.url)) {
        auth.handleUnauthorized();
      }
      return throwError(() => err);
    }),
  );
};
