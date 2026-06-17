import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { AuthService } from './auth.service';
import { USE_MOCK_API } from '../api/api.config';
import type { Principal } from '../api/models';
import { mockWindowLocation, type LocationMock } from '../../../testing/location-mock';

const PRINCIPAL: Principal = {
  sub: '1',
  display_name: 'Mia',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['vote.cast'],
  groups: [],
};

describe('AuthService', () => {
  let auth: AuthService;
  let http: HttpTestingController;
  let location: LocationMock;
  let assign: jest.Mock<void, [string]>;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
    location = mockWindowLocation();
    assign = location.assign;
  });

  afterEach(() => {
    http.verify();
    location.restore();
  });

  it('loads the principal once and exposes permission checks', () => {
    auth.ensureLoaded().subscribe();
    auth.ensureLoaded().subscribe(); // memoisiert → nur ein HTTP-Call
    http.expectOne('/api/auth/me').flush(PRINCIPAL);

    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.can('vote.cast')).toBe(true);
    expect(auth.can('admin.config')).toBe(false);
    expect(auth.canAny('admin.config', 'vote.cast')).toBe(true);
    expect(auth.canAny('admin.config')).toBe(false);
    expect(auth.displayName()).toBe('Mia');
    expect(auth.roles()).toEqual(['member']);
  });

  it('falls back to email then placeholder for the display name', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush({ ...PRINCIPAL, display_name: null });
    expect(auth.displayName()).toBe('mia@stupa');
  });

  it('stays anonymous when /me returns 401', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    expect(auth.isAuthenticated()).toBe(false);
    expect(auth.can('vote.cast')).toBe(false);
    expect(auth.displayName()).toBe('—');
  });

  it('redirects to the OIDC login endpoint', () => {
    auth.login();
    expect(assign).toHaveBeenCalledWith('/api/auth/login');
  });

  it('logs out, clears the principal and follows the RP logout url', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);

    auth.logout();
    http.expectOne('/api/auth/logout').flush({ logout_url: 'https://idp/logout' });

    expect(auth.isAuthenticated()).toBe(false);
    expect(assign).toHaveBeenCalledWith('https://idp/logout');
  });

  it('logs out to home when no RP logout url is returned', () => {
    auth.logout();
    http.expectOne('/api/auth/logout').flush({ logout_url: null });
    expect(assign).toHaveBeenCalledWith('/');
  });

  it('logs out gracefully even if the request errors', () => {
    auth.logout();
    http
      .expectOne('/api/auth/logout')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(assign).toHaveBeenCalledWith('/');
  });

  it('exposes derived principal signals (id, gremien, scoped/manage/substitute flags)', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush({
      ...PRINCIPAL,
      gremien: [{ id: 'g1', name: 'StuPa', slug: 'stupa' }],
      session_manage_gremien: ['g1'],
      has_scoped_budget_view: true,
      in_substitute_pool: true,
    });
    expect(auth.userId()).toBe('1');
    expect(auth.gremien()).toEqual([{ id: 'g1', name: 'StuPa', slug: 'stupa' }]);
    expect(auth.sessionManageGremien()).toEqual(['g1']);
    expect(auth.hasScopedBudgetView()).toBe(true);
    expect(auth.inSubstitutePool()).toBe(true);
  });

  it('defaults the derived signals when the principal omits them / is anonymous', () => {
    // Anonymous: all derived signals use their empty/false fallbacks.
    expect(auth.userId()).toBeNull();
    expect(auth.gremien()).toEqual([]);
    expect(auth.roles()).toEqual([]);
    expect(auth.sessionManageGremien()).toEqual([]);
    expect(auth.hasScopedBudgetView()).toBe(false);
    expect(auth.inSubstitutePool()).toBe(false);

    auth.ensureLoaded().subscribe();
    // Authenticated but with the optional fields absent → still the fallbacks.
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    expect(auth.gremien()).toEqual([]);
    expect(auth.sessionManageGremien()).toEqual([]);
    expect(auth.hasScopedBudgetView()).toBe(false);
    expect(auth.inSubstitutePool()).toBe(false);
  });

  it('falls back to the placeholder display name when name and email are blank', () => {
    auth.ensureLoaded().subscribe();
    http
      .expectOne('/api/auth/me')
      .flush({ ...PRINCIPAL, display_name: null, email: '' });
    expect(auth.displayName()).toBe('—');
  });

  it('ensureAuthenticated maps the principal presence to a boolean', () => {
    let authed: boolean | undefined;
    auth.ensureAuthenticated().subscribe((v) => (authed = v));
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    expect(authed).toBe(true);
  });

  it('ensureAuthenticated is false for anonymous (401) sessions', () => {
    let authed: boolean | undefined;
    auth.ensureAuthenticated().subscribe((v) => (authed = v));
    http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    expect(authed).toBe(false);
  });

  it('grants admins every permission via can()/canAny()', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush({ ...PRINCIPAL, roles: ['admin'], permissions: [] });
    expect(auth.can('anything.at.all')).toBe(true);
    expect(auth.canAny('whatever')).toBe(true);
    // Empty permission list → canAny is vacuously true (any session passes).
    expect(auth.canAny()).toBe(true);
  });

  it('re-loads the principal after logout clears the memoised observable', () => {
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);

    auth.logout();
    http.expectOne('/api/auth/logout').flush({ logout_url: null });

    // The cached principal$ was reset → a fresh ensureLoaded triggers a new /me.
    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    expect(auth.isAuthenticated()).toBe(true);
  });

  it('handleUnauthorized re-authenticates only when a principal was present', () => {
    auth.handleUnauthorized();
    expect(assign).not.toHaveBeenCalled();

    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    auth.handleUnauthorized();

    expect(auth.isAuthenticated()).toBe(false);
    expect(assign).toHaveBeenCalledWith('/api/auth/login');
  });
});
