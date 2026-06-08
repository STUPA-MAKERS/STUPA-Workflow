import { Injectable, computed, inject, signal } from '@angular/core';
import { type Observable, of, shareReplay, tap } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiClient } from '../api/api-client.service';
import type { Principal } from '../api/models';

/**
 * Auth-State. Principal aus GET /api/auth/me (Session-Cookie, OIDC). RBAC ist
 * **nie** FE-autoritativ (security.md §2): `can()`/Nav-Gating sind reine UX —
 * der Server prüft jede Route per `require_principal`. `ensureLoaded()` lädt den
 * Principal genau einmal (memoisiert), damit Route-Guards synchron entscheiden.
 *
 * Beide Sessions (OIDC-principal, Magic-Link-applicant) laufen ausschließlich
 * über HttpOnly-Cookies (security.md §1) — kein Token im JS-Storage, daher kein
 * XSS-Exfiltrationspfad. Der auth-Interceptor sendet sie via `withCredentials`.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiClient);

  private readonly _principal = signal<Principal | null>(null);
  private principal$?: Observable<Principal | null>;

  readonly principal = this._principal.asReadonly();
  readonly isAuthenticated = computed(() => this._principal() !== null);

  /** Anzeigename (Fallback: Mail → "—"). */
  readonly displayName = computed(() => {
    const p = this._principal();
    return p?.display_name || p?.email || '—';
  });
  readonly roles = computed(() => this._principal()?.roles ?? []);
  /** Gremien des angemeldeten Principals (#5) — für die »Meine Gremien«-Ansicht. */
  readonly gremien = computed(() => this._principal()?.gremien ?? []);

  /**
   * Lädt den Principal genau einmal und cached das Ergebnis (`shareReplay`).
   * 401/anonym → `null`. Mehrfachaufrufe (App-Init + Guards) teilen sich den Call.
   */
  ensureLoaded(): Observable<Principal | null> {
    this.principal$ ??= this.api.me().pipe(
      catchError(() => of(null)),
      tap((p) => this._principal.set(p)),
      shareReplay(1),
    );
    return this.principal$;
  }

  /** Convenience für Guards: `true`, sobald ein Principal vorliegt. */
  ensureAuthenticated(): Observable<boolean> {
    return this.ensureLoaded().pipe(map((p) => p !== null));
  }

  /** Permission-Check für RBAC-Guards/Nav-Gating (UX, nicht autoritativ). */
  can(permission: string): boolean {
    return this._principal()?.permissions.includes(permission) ?? false;
  }

  /** `true`, wenn der Principal mindestens eine der Permissions besitzt. */
  canAny(...permissions: string[]): boolean {
    return permissions.length === 0 || permissions.some((p) => this.can(p));
  }

  /** Startet den OIDC-Login (Full-Redirect zu Keycloak via Backend). */
  login(): void {
    window.location.assign('/api/auth/login');
  }

  /**
   * Beendet die Server-Session und folgt — falls vom Backend geliefert — der
   * RP-Initiated-Logout-URL (Keycloak SSO), sonst zurück zur Startseite.
   */
  logout(): void {
    this.api
      .logout()
      .pipe(catchError(() => of({ logout_url: null })))
      .subscribe((res) => {
        this._principal.set(null);
        this.principal$ = undefined;
        window.location.assign(res.logout_url ?? '/');
      });
  }

  /**
   * 401 auf einem geschützten Request: Session ist weg/abgelaufen → Principal
   * verwerfen und neu anmelden (security.md §2). Vom auth-Interceptor gerufen.
   */
  handleUnauthorized(): void {
    if (this._principal() === null) return;
    this._principal.set(null);
    this.principal$ = undefined;
    this.login();
  }
}
