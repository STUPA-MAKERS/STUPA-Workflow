import type { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';

/**
 * Hängt Auth an ausgehende `/api`-Requests:
 * - `withCredentials` → HttpOnly-Session-Cookie (OIDC-Principal, api.md §1).
 * - Magic-Link-Applicant-Token als `Authorization: Bearer` (falls vorhanden).
 * Keine Tokens an Fremd-Hosts (nur same-origin `/api`).
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.includes('/api/')) return next(req);

  const auth = inject(AuthService);
  const applicantToken = auth.applicantToken();

  const authed = req.clone({
    withCredentials: true,
    setHeaders: applicantToken ? { Authorization: `Bearer ${applicantToken}` } : {},
  });
  return next(authed);
};
