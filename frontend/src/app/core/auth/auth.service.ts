import { Injectable, computed, inject, signal } from '@angular/core';
import { catchError, of, tap } from 'rxjs';
import { ApiClient } from '../api/api-client.service';
import type { Principal } from '../api/models';

const APPLICANT_TOKEN_KEY = 'ap.applicantToken';

/**
 * Auth-State (Skelett). Principal aus GET /api/auth/me (Session-Cookie).
 * Applicant-Magic-Link-Token wird (kurzlebig) gehalten und vom auth-Interceptor
 * als Bearer mitgesendet. RBAC-Helfer (`can`) für künftige Route-Guards.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiClient);

  private readonly _principal = signal<Principal | null>(null);
  private readonly _applicantToken = signal<string | null>(this.readToken());

  readonly principal = this._principal.asReadonly();
  readonly applicantToken = this._applicantToken.asReadonly();
  readonly isAuthenticated = computed(() => this._principal() !== null);

  /** Lädt den Principal; setzt bei 401 still `null` (anonym). */
  loadPrincipal(): void {
    this.api
      .me()
      .pipe(
        tap((p) => this._principal.set(p)),
        catchError(() => {
          this._principal.set(null);
          return of(null);
        }),
      )
      .subscribe();
  }

  /** Permission-Check für RBAC-Guards. */
  can(permission: string): boolean {
    return this._principal()?.permissions.includes(permission) ?? false;
  }

  setApplicantToken(token: string | null): void {
    this._applicantToken.set(token);
    try {
      if (token) sessionStorage.setItem(APPLICANT_TOKEN_KEY, token);
      else sessionStorage.removeItem(APPLICANT_TOKEN_KEY);
    } catch {
      /* ignore */
    }
  }

  login(): void {
    window.location.href = '/api/auth/login';
  }

  private readToken(): string | null {
    try {
      return sessionStorage.getItem(APPLICANT_TOKEN_KEY);
    } catch {
      return null;
    }
  }
}
