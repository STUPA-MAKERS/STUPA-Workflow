import { Injectable, Injector, computed, inject, signal } from '@angular/core';
import { type Observable, of, shareReplay, tap } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiClient } from '../api/api-client.service';
import type { Principal } from '../api/models';
import { LOCATION } from '../browser/location.token';

/**
 * Auth state. Principal from GET /api/auth/me (session cookie, OIDC). RBAC is
 * never FE-authoritative: `can()`/nav gating are pure UX — the server checks
 * every route via `require_principal`. `ensureLoaded()` loads the principal
 * exactly once (memoized) so route guards can decide synchronously.
 *
 * Both sessions (OIDC principal, magic-link applicant) run exclusively over
 * HttpOnly cookies — no token in JS storage, hence no XSS exfiltration path. The
 * auth interceptor sends them via `withCredentials`.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  // Resolve `ApiClient` (→ HttpClient) lazily, not in the field initializer:
  // otherwise the root `AuthService` pulls HttpClient into every component that
  // injects it only for `can()`/`roles()`, and their specs fail with NG0201.
  private readonly injector = inject(Injector);
  private readonly location = inject(LOCATION);
  private get api(): ApiClient {
    return this.injector.get(ApiClient);
  }

  private readonly _principal = signal<Principal | null>(null);
  private principal$?: Observable<Principal | null>;

  readonly principal = this._principal.asReadonly();
  readonly isAuthenticated = computed(() => this._principal() !== null);

  /** Display name (fallback: email → "—"). */
  readonly displayName = computed(() => {
    const p = this._principal();
    return p?.display_name || p?.email || '—';
  });
  /** Principal id (`sub`) of the logged-in user — e.g. compared with a meeting's
   *  assigned protokollant. `null` while anonymous. */
  readonly userId = computed(() => this._principal()?.sub ?? null);
  readonly roles = computed(() => this._principal()?.roles ?? []);
  /** Gremien of the logged-in principal — for the "My gremien" view. */
  readonly gremien = computed(() => this._principal()?.gremien ?? []);
  /** Gremien the principal MANAGES via their gremium role (`session.manage`,
   *  e.g. board/manager) — gates "create meeting" without the global
   *  `meeting.manage` permission. Pure UX, the server decides. */
  readonly sessionManageGremien = computed(
    () => this._principal()?.session_manage_gremien ?? [],
  );
  /** At least one cost centre is assigned to a member gremium as a visibility
   *  root — budget tab without global budget.* rights. */
  readonly hasScopedBudgetView = computed(
    () => this._principal()?.has_scoped_budget_view === true,
  );
  /** Principal is in ≥1 substitute pool — may see the meeting timeline of their
   *  gremien (live channel only via a concrete delegation). */
  readonly inSubstitutePool = computed(
    () => this._principal()?.in_substitute_pool === true,
  );

  /**
   * Loads the principal exactly once and caches the result (`shareReplay`).
   * 401/anonymous → `null`. Repeated calls (app init + guards) share the call.
   */
  ensureLoaded(): Observable<Principal | null> {
    this.principal$ ??= this.api.me().pipe(
      catchError(() => of(null)),
      tap((p) => this._principal.set(p)),
      shareReplay(1),
    );
    return this.principal$;
  }

  /** Convenience for guards: `true` once a principal is present. */
  ensureAuthenticated(): Observable<boolean> {
    return this.ensureLoaded().pipe(map((p) => p !== null));
  }

  /** Permission check for RBAC guards/nav gating (UX, not authoritative).
   *  ``admin`` has all rights (like the backend). */
  can(permission: string): boolean {
    const p = this._principal();
    if (!p) return false;
    return p.roles.includes('admin') || p.permissions.includes(permission);
  }

  /** `true` if the principal holds at least one of the permissions. */
  canAny(...permissions: string[]): boolean {
    return permissions.length === 0 || permissions.some((p) => this.can(p));
  }

  /** Starts the OIDC login (full redirect to Keycloak via the backend). */
  login(): void {
    this.location.assign('/api/auth/login');
  }

  /**
   * Ends the server session and follows — if the backend supplies one — the
   * RP-initiated logout URL (Keycloak SSO), otherwise back to the home page.
   */
  logout(): void {
    this.api
      .logout()
      .pipe(catchError(() => of({ logout_url: null })))
      .subscribe((res) => {
        this._principal.set(null);
        this.principal$ = undefined;
        this.location.assign(res.logout_url ?? '/');
      });
  }

  /**
   * 401 on a protected request: the session is gone/expired → drop the principal
   * and log in again. Called by the auth interceptor.
   */
  handleUnauthorized(): void {
    if (this._principal() === null) return;
    this._principal.set(null);
    this.principal$ = undefined;
    this.login();
  }
}
