import { type HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { AuthService } from './auth.service';

/** Double-Submit-CSRF: Cookie (lesbar) → gespiegelt im Header (security.md §10). */
const CSRF_COOKIE = 'XSRF-TOKEN';
const CSRF_HEADER = 'X-XSRF-TOKEN';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Same-origin-`/api`? Nur dann Session-Cookie + CSRF-Header anhängen — sonst
 * würden Credentials an Fremd-Hosts leaken. Relative URLs (`/api/...`) sind per
 * Definition same-origin; absolute URLs müssen den Browser-Origin exakt treffen.
 */
function isSameOriginApi(url: string): boolean {
  if (url.startsWith('/api/')) return true;
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url);
      return parsed.origin === window.location.origin && parsed.pathname.startsWith('/api/');
    } catch {
      return false;
    }
  }
  return false;
}

/** Endpunkte, deren 401 erwartbar ist → kein erzwungener Re-Login (Loop/Race). */
function skipReloginOn(url: string): boolean {
  return url.includes('/auth/me') || url.includes('/auth/login') || url.includes('/auth/logout');
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Hängt Auth an ausgehende same-origin `/api`-Requests:
 * - `withCredentials` → HttpOnly-Cookies (OIDC-principal / Magic-Link-applicant,
 *   api.md §1). Es liegt **kein** Token im JS-Storage; nichts via XSS abgreifbar.
 * - **CSRF**: bei schreibenden Methoden das `XSRF-TOKEN`-Cookie als Header
 *   spiegeln (Double-Submit, security.md §10).
 * - **401**: abgelaufene/fehlende Session → Principal verwerfen + Re-Login
 *   (außer bei den auth-Endpunkten, deren 401 erwartbar ist).
 * Fremd-Origins bleiben unangetastet — keine Credentials/Header nach außen.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isSameOriginApi(req.url)) return next(req);

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
