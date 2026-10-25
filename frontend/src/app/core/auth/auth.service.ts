import { Injectable, Injector, computed, inject, signal } from '@angular/core';
import { type Observable, of, shareReplay, tap } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiClient } from '../api/api-client.service';
import type { Principal } from '../api/models';
import { LOCATION } from '../browser/location.token';
import { IS_INSTALLED_APP } from '../browser/installed-app.token';
import { HttpCacheService } from '@core/cache/http-cache.service';

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
  private readonly isInstalledApp = inject(IS_INSTALLED_APP);
  private readonly cache = inject(HttpCacheService);
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
   *  example board or manager). It gates "create meeting". This is only UX. The
   *  server decides. */
  readonly sessionManageGremien = computed(
    () => this._principal()?.session_manage_gremien ?? [],
  );
  /** The principal holds the global `admin` role. The admin bypasses every gremium
   *  permission, as in the backend. */
  readonly isAdmin = computed(() => this.roles().includes('admin'));
  /** Gremium id to the gremium permissions of the principal in that gremium. */
  readonly gremiumPermissions = computed(
    () => this._principal()?.gremium_permissions ?? {},
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
  /** The principal reported a ticket: the tab "Tickets" shows its own tickets. A report
   *  of this session sets it at once (`markReportedTicket`). */
  readonly hasReportedTickets = computed(
    () => this._principal()?.has_reported_tickets === true,
  );

  /** A report went out with this session: the tab "Tickets" shows from now on. */
  markReportedTicket(): void {
    const p = this._principal();
    if (p && !p.has_reported_tickets) this._principal.set({ ...p, has_reported_tickets: true });
  }

  /**
   * Loads the principal exactly once and caches the result with `shareReplay`.
   *
   * A 401 or an anonymous user gives `null`. Repeated calls from the app start and
   * from the guards share the one call.
   */
  ensureLoaded(): Observable<Principal | null> {
    this.principal$ ??= this.api.me().pipe(
      catchError(() => of(null)),
      tap((p) => {
        this._principal.set(p);
        if (p) writeLoginMark(null);
      }),
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

  /** Gremium permission check (`session.manage`, `protocol.write`, …) in ONE
   *  gremium. The admin passes. It is UX only and not authoritative. */
  canInGremium(gremiumId: string, permission: string): boolean {
    if (this.isAdmin()) return true;
    return (this.gremiumPermissions()[gremiumId] ?? []).includes(permission);
  }

  /** Gremium permission check in ANY gremium of the principal. The admin passes. */
  canInAnyGremium(permission: string): boolean {
    if (this.isAdmin()) return true;
    return Object.values(this.gremiumPermissions()).some((perms) =>
      perms.includes(permission),
    );
  }

  /** `true` if the principal holds at least one of the permissions. */
  canAny(...permissions: string[]): boolean {
    return permissions.length === 0 || permissions.some((p) => this.can(p));
  }

  /**
   * Starts the OIDC login. It redirects the whole page to the IdP via the backend.
   *
   * The installed app (PWA) sends `?client=pwa`, because the server keeps the session
   * of the installed app longer than the session of a browser tab. Every login of the
   * app goes through this method, so the guard, the 401 re-login and each login button
   * send the same parameters.
   *
   * `returnTo` is the app URL to open after the login (the guard passes the URL of the
   * blocked navigation). Without it, the login returns to the current page. A link from
   * a mail, such as `/applications/<id>#comment-<id>`, then still opens its target.
   */
  login(returnTo?: string): void {
    const current = `${this.location.pathname}${this.location.search}${this.location.hash}`;
    writeLoginMark(Date.now());
    this.location.assign(this.loginUrl(loginReturnTo(returnTo ?? current)));
  }

  /**
   * `true` once if a login started in this tab less than a minute ago and still gave no
   * principal. The guard then goes home instead of starting the login again: the login
   * returns to the guarded page, so a `/auth/me` that keeps failing after a good login
   * (a server error, a cookie the browser refuses) would otherwise loop through the IdP.
   * The call clears the mark, so the next attempt can log in again.
   */
  loginJustFailed(): boolean {
    const started = readLoginMark();
    writeLoginMark(null);
    return started !== null && Date.now() - started < LOGIN_LOOP_WINDOW_MS;
  }

  /** The URL of the login start, with `client=pwa` for the installed app and `returnTo`. */
  private loginUrl(returnTo: string | null): string {
    const params = new URLSearchParams();
    if (this.isInstalledApp()) params.set('client', 'pwa');
    if (returnTo) params.set('returnTo', returnTo);
    const query = params.toString();
    return query ? `/api/auth/login?${query}` : '/api/auth/login';
  }

  /**
   * Ends the server session.
   *
   * If the backend supplies an RP-initiated logout URL for the IdP SSO, the
   * browser follows it. Otherwise the browser goes to the home page.
   *
   * Cached responses are scoped to whoever asked for them, so the next person at this browser must
   * not inherit a list they were never allowed to see.
   */
  logout(): void {
    this.api
      .logout()
      .pipe(catchError(() => of({ logout_url: null })))
      .subscribe((res) => {
        this._principal.set(null);
        this.principal$ = undefined;
        this.cache.clear();
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

/**
 * The part of an app URL that the login may carry to the server and back.
 *
 * The path and the query stay, without a magic-link token (`t`). The fragment stays only
 * when it is a plain anchor (`#comments`, `#comment-<id>`), because the guest page keeps
 * its token in the fragment (`#t=<token>`) and a token must not reach a server log. The
 * start page and paths under `/api` give `null`: the login then goes home, as before.
 */
export function loginReturnTo(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url, 'http://app.invalid');
  } catch {
    return null;
  }
  if (parsed.origin !== 'http://app.invalid') return null;
  const path = parsed.pathname;
  if (path === '/api' || path.startsWith('/api/')) return null;
  parsed.searchParams.delete('t');
  const search = parsed.searchParams.toString();
  const hash = /^#[A-Za-z][\w-]*$/.test(parsed.hash) ? parsed.hash : '';
  const out = `${path}${search ? `?${search}` : ''}${hash}`;
  return out === '/' ? null : out;
}

const LOGIN_MARK = 'auth.loginStartedAt';
const LOGIN_LOOP_WINDOW_MS = 60_000;

/** The start time of the last login in this tab, or `null`. Storage may be blocked. */
function readLoginMark(): number | null {
  try {
    const raw = sessionStorage.getItem(LOGIN_MARK);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

function writeLoginMark(value: number | null): void {
  try {
    if (value === null) sessionStorage.removeItem(LOGIN_MARK);
    else sessionStorage.setItem(LOGIN_MARK, String(value));
  } catch {
    /* Blocked storage: no loop guard, the login still works. */
  }
}
