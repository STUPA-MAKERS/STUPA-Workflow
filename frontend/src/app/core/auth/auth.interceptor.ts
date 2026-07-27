import { type HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { LOCATION } from '../browser/location.token';
import { AuthService } from './auth.service';

/** Double-submit CSRF. The client reads the cookie and mirrors it in the header. */
const CSRF_COOKIE = 'XSRF-TOKEN';
const CSRF_HEADER = 'X-XSRF-TOKEN';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Tells whether the URL points at the same-origin `/api`. Only then may the caller
 * attach the session cookie and the CSRF header. Otherwise the credentials leak to
 * a foreign host. A relative URL (`/api/...`) is same-origin by definition. An
 * absolute URL must match the browser origin exactly.
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

/** Endpoints where a 401 is expected. A forced re-login would loop or race. */
function skipReloginOn(url: string): boolean {
  return url.includes('/auth/me') || url.includes('/auth/login') || url.includes('/auth/logout');
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Attaches auth to an outgoing same-origin `/api` request:
 * - `withCredentials` sends the HttpOnly cookies of the OIDC principal or of the
 *   magic-link applicant. No token sits in JS storage, so XSS can steal nothing.
 * - CSRF: for a writing method it mirrors the `XSRF-TOKEN` cookie into a header.
 *   This is the double-submit pattern.
 * - 401: the session expired or is missing. The interceptor drops the principal
 *   and starts the re-login. It skips the auth endpoints, where a 401 is expected.
 *
 * It leaves a foreign origin untouched. No credential and no header leaves.
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
