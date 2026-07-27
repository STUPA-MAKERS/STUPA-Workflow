import { Injectable, Injector, computed, inject, signal } from '@angular/core';
import { type Observable, of, shareReplay, tap } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiClient } from '../api/api-client.service';
import type { Principal } from '../api/models';
import { LOCATION } from '../browser/location.token';

/**
 * Auth state. The principal comes from GET /api/auth/me over the OIDC session
 * cookie. RBAC is never authoritative on the frontend. `can()` and the nav gating
 * are only UX. The server checks every route through `require_principal`.
 * `ensureLoaded()` loads the principal exactly once and memoizes it, so a route
 * guard can decide synchronously.
 *
 * Both sessions, the OIDC principal and the magic-link applicant, run only over
 * HttpOnly cookies. No token sits in JS storage, so XSS has no path to steal one.
 * The auth interceptor sends the cookies through `withCredentials`.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  // Resolve `ApiClient`, and with it `HttpClient`, lazily and not in the field
  // initializer. Otherwise the root `AuthService` pulls `HttpClient` into every
  // component that injects it only for `can()` or `roles()`. Their specs then fail
  // with NG0201.
  private readonly injector = inject(Injector);
  private readonly location = inject(LOCATION);
  private get api(): ApiClient {
    return this.injector.get(ApiClient);
  }

  private readonly _principal = signal<Principal | null>(null);
  private principal$?: Observable<Principal | null>;

  readonly principal = this._principal.asReadonly();
  readonly isAuthenticated = computed(() => this._principal() !== null);

  /** Display name. It falls back to the email and then to "—". */
  readonly displayName = computed(() => {
    const p = this._principal();
    return p?.display_name || p?.email || '—';
  });
  /** Principal id (`sub`) of the logged-in user. The app compares it with the
   *  assigned protokollant of a meeting. It is `null` while anonymous. */
  readonly userId = computed(() => this._principal()?.sub ?? null);
  readonly roles = computed(() => this._principal()?.roles ?? []);
  /** Gremien of the logged-in principal. The "My gremien" view uses them. */
  readonly gremien = computed(() => this._principal()?.gremien ?? []);
  /** Gremien the principal MANAGES through a gremium role (`session.manage`, for
   *  example board or manager). It gates "create meeting" without the global
   *  `meeting.manage` permission. This is only UX. The server decides. */
  readonly sessionManageGremien = computed(
    () => this._principal()?.session_manage_gremien ?? [],
  );
  /** At least one cost center is assigned to a member gremium as a visibility
   *  root. The budget tab opens without global budget.* permissions. */
  readonly hasScopedBudgetView = computed(
    () => this._principal()?.has_scoped_budget_view === true,
  );
  /** The principal is in at least one substitute pool. The principal may see the
   *  meeting timeline of their gremien. The live channel still needs a concrete
   *  delegation. */
  readonly inSubstitutePool = computed(
    () => this._principal()?.in_substitute_pool === true,
  );

  /**
   * Loads the principal exactly once and caches the result with `shareReplay`.
   *
   * A 401 or an anonymous user gives `null`. Repeated calls from the app start and
   * from the guards share the one call.
   */
  ensureLoaded(): Observable<Principal | null> {
    this.principal$ ??= this.api.me().pipe(
      catchError(() => of(null)),
      tap((p) => this._principal.set(p)),
      shareReplay(1),
    );
    return this.principal$;
  }

  /** Helper for guards. It gives `true` as soon as a principal exists. */
  ensureAuthenticated(): Observable<boolean> {
    return this.ensureLoaded().pipe(map((p) => p !== null));
  }

  /** Permission check for the RBAC guards and the nav gating. It is UX only and
   *  not authoritative. The `admin` role holds every permission, as in the backend. */
  can(permission: string): boolean {
    const p = this._principal();
    if (!p) return false;
    return p.roles.includes('admin') || p.permissions.includes(permission);
  }

  /** `true` if the principal holds at least one of the permissions. */
  canAny(...permissions: string[]): boolean {
    return permissions.length === 0 || permissions.some((p) => this.can(p));
  }

  /** Starts the OIDC login. It redirects the whole page to Keycloak via the backend. */
  login(): void {
    this.location.assign('/api/auth/login');
  }

  /**
   * Ends the server session.
   *
   * If the backend supplies an RP-initiated logout URL for the Keycloak SSO, the
   * browser follows it. Otherwise the browser goes to the home page.
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
   * Handles a 401 on a protected request.
   *
   * The session is gone or expired. The method drops the principal and starts the
   * login again. The auth interceptor calls it.
   */
  handleUnauthorized(): void {
    if (this._principal() === null) return;
    this._principal.set(null);
    this.principal$ = undefined;
    this.login();
  }
}
