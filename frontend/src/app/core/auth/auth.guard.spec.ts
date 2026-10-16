import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {
  type ActivatedRouteSnapshot,
  type RouterStateSnapshot,
  UrlTree,
  provideRouter,
} from '@angular/router';
import { isObservable, type Observable } from 'rxjs';
import { authGuard } from './auth.guard';
import { routes } from '../../app.routes';
import { USE_MOCK_API } from '../api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Principal } from '../api/models';
import {
  createLocationMock,
  provideLocationMock,
  type LocationMock,
} from '../../../testing/location-mock';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read'],
  groups: [],
};

describe('authGuard', () => {
  let http: HttpTestingController;
  let location: LocationMock;
  let assign: jest.Mock<void, [string]>;

  beforeEach(() => {
    sessionStorage.clear();
    location = createLocationMock();
    assign = location.assign;
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        provideLocationMock(location),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  /** Runs the guard, flushes the `/me` probe and returns the result. */
  function run(
    data: Record<string, unknown>,
    principal: Principal | null,
  ): boolean | UrlTree {
    let result!: boolean | UrlTree;
    TestBed.runInInjectionContext(() => {
      const out = authGuard(
        { data } as unknown as ActivatedRouteSnapshot,
        {} as RouterStateSnapshot,
      );
      (out as Observable<boolean | UrlTree>).subscribe((r) => (result = r));
    });
    http.expectOne('/api/auth/me').flush(principal, principal ? {} : { status: 401, statusText: 'Unauthorized' });
    return result;
  }

  it('returns an Observable', () => {
    TestBed.runInInjectionContext(() => {
      const out = authGuard(
        { data: {} } as unknown as ActivatedRouteSnapshot,
        {} as RouterStateSnapshot,
      );
      expect(isObservable(out)).toBe(true);
      (out as Observable<unknown>).subscribe();
    });
    http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
  });

  it('redirects anonymous users to OIDC login and blocks the route', () => {
    expect(run({}, null)).toBe(false);
    expect(assign).toHaveBeenCalledWith('/api/auth/login');
  });

  it('returns to the blocked target after the login', () => {
    let result!: boolean | UrlTree;
    TestBed.runInInjectionContext(() => {
      const out = authGuard(
        { data: {} } as unknown as ActivatedRouteSnapshot,
        { url: '/applications/a1#comment-c1' } as RouterStateSnapshot,
      );
      (out as Observable<boolean | UrlTree>).subscribe((r) => (result = r));
    });
    http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    expect(result).toBe(false);
    expect(assign).toHaveBeenCalledWith('/api/auth/login?returnTo=%2Fapplications%2Fa1%23comment-c1');
  });

  it('goes home instead of looping when a login just came back without a session', () => {
    sessionStorage.setItem('auth.loginStartedAt', String(Date.now() - 5_000));
    const result = run({}, null);
    expect(result).toBeInstanceOf(UrlTree);
    expect(String(result)).toBe('/');
    expect(assign).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('auth.loginStartedAt')).toBeNull();
  });

  it('logs in again when the last login is older than a minute', () => {
    sessionStorage.setItem('auth.loginStartedAt', String(Date.now() - 120_000));
    expect(run({}, null)).toBe(false);
    expect(assign).toHaveBeenCalledWith('/api/auth/login');
    expect(sessionStorage.getItem('auth.loginStartedAt')).not.toBeNull();
  });

  it('allows an authenticated user when no permission is required', () => {
    expect(run({}, MEMBER)).toBe(true);
  });

  it('allows when the principal holds a required permission', () => {
    expect(run({ permission: 'application.read' }, MEMBER)).toBe(true);
  });

  it('allows when the principal holds any of several required permissions', () => {
    expect(run({ permission: ['admin.config', 'application.read'] }, MEMBER)).toBe(true);
  });

  it('redirects to the forbidden page and toasts when the permission is missing', () => {
    const toast = TestBed.inject(ToastService);
    const toastSpy = jest.spyOn(toast, 'error');
    const result = run({ permission: 'admin.config' }, MEMBER);
    expect(result).toBeInstanceOf(UrlTree);
    expect((result as UrlTree).toString()).toBe('/forbidden');
    expect(toastSpy).toHaveBeenCalled();
  });

  it('allows a committee member onto allowCommitteeMember routes without the permission', () => {
    const inCommittee: Principal = {
      ...MEMBER,
      permissions: [],
      gremien: [{ id: 'g1', name: 'StuPa', slug: 'stupa' }],
    };
    // Mirrors the real /meetings route data.
    const data = { gremiumPermission: ['session.manage'], allowCommitteeMember: true };
    expect(run(data, inCommittee)).toBe(true);
  });

  it('still forbids allowCommitteeMember routes when the user is in no committee', () => {
    const noCommittee: Principal = { ...MEMBER, permissions: [], gremien: [] };
    const data = { gremiumPermission: ['session.manage'], allowCommitteeMember: true };
    expect(run(data, noCommittee)).toBeInstanceOf(UrlTree);
  });

  it('allows gremiumPermission routes with the permission in any gremium', () => {
    const chair: Principal = {
      ...MEMBER,
      gremium_permissions: { g1: ['session.manage'] },
    };
    expect(run({ gremiumPermission: 'session.manage' }, chair)).toBe(true);
  });

  it('forbids gremiumPermission routes without the permission in any gremium', () => {
    const member: Principal = { ...MEMBER, gremium_permissions: { g1: ['vote.cast'] } };
    expect(run({ gremiumPermission: 'session.manage' }, member)).toBeInstanceOf(UrlTree);
  });

  it('lets the admin onto gremiumPermission routes', () => {
    const admin: Principal = { ...MEMBER, roles: ['admin'] };
    expect(run({ gremiumPermission: 'session.manage' }, admin)).toBe(true);
  });

  it('accepts either a global or a gremium permission when a route names both', () => {
    const viewer: Principal = { ...MEMBER, permissions: ['meeting.view_all'] };
    const data = { permission: ['meeting.view_all'], gremiumPermission: ['session.manage'] };
    expect(run(data, viewer)).toBe(true);
  });

  it('allows scoped-budget-view members onto allowScopedBudgetView routes', () => {
    const scoped: Principal = {
      ...MEMBER,
      permissions: [],
      has_scoped_budget_view: true,
    };
    const data = { permission: ['budget.view'], allowScopedBudgetView: true };
    expect(run(data, scoped)).toBe(true);
  });

  it('forbids allowScopedBudgetView routes when the principal lacks the scoped view', () => {
    const noScope: Principal = {
      ...MEMBER,
      permissions: [],
      has_scoped_budget_view: false,
    };
    const data = { permission: ['budget.view'], allowScopedBudgetView: true };
    expect(run(data, noScope)).toBeInstanceOf(UrlTree);
  });

  describe('the tickets', () => {
    const tickets = routes.flatMap((r) => r.children ?? []).find((c) => c.path === 'tickets')!;
    const plain: Principal = { ...MEMBER, permissions: [], gremien: [] };

    it('let a reporter in without ticket.manage', () => {
      expect(run({ ...tickets.data }, { ...plain, has_reported_tickets: true })).toBe(true);
    });

    it('stay closed to anybody else without ticket.manage', () => {
      expect(run({ ...tickets.data }, plain)).not.toBe(true);
    });
  });

  it('lets any authenticated user onto allowAuthenticated routes', () => {
    const anyUser: Principal = { ...MEMBER, permissions: [], gremien: [] };
    const data = { permission: ['budget.view'], allowAuthenticated: true };
    expect(run(data, anyUser)).toBe(true);
  });

  describe('the vote routes, for a reader of one vote', () => {
    // A reader with `application.read` and no gremium voting right opens a vote at
    // /voting/:id. Every way back goes to /voting, so the list child must let them in
    // too. The empty-path child inherits the data of its parent (`emptyOnly`).
    const shell = routes.find((r) => r.children?.some((c) => c.path === 'voting'));
    const voting = shell!.children!.find((c) => c.path === 'voting')!;
    const child = (path: string) => voting.children!.find((c) => c.path === path)!;
    const reader: Principal = { ...MEMBER, gremien: [] };

    it('lets them onto the list (/voting)', () => {
      expect(run({ ...voting.data, ...child('').data }, reader)).toBe(true);
    });

    it('lets them onto the vote (/voting/:id)', () => {
      expect(run({ ...child(':id').data }, reader)).toBe(true);
    });

    it('keeps the gate of the parent data, which the navigation entry reads', () => {
      expect(run({ ...voting.data }, reader)).toBeInstanceOf(UrlTree);
    });
  });

});
