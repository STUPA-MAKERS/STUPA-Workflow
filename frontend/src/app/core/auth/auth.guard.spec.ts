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
import { USE_MOCK_API } from '../api/api.config';
import { ToastService } from '@shared/ui/toast/toast.service';
import type { Principal } from '../api/models';
import { mockWindowLocation, type LocationMock } from '../../../testing/location-mock';

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
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    location = mockWindowLocation();
    assign = location.assign;
  });

  afterEach(() => {
    http.verify();
    location.restore();
  });

  /** Führt den Guard aus, flusht den `/me`-Probe und liefert das Ergebnis. */
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

  it('allows an authenticated user when no permission is required', () => {
    expect(run({}, MEMBER)).toBe(true);
  });

  it('allows when the principal holds a required permission', () => {
    expect(run({ permission: 'application.read' }, MEMBER)).toBe(true);
  });

  it('allows when the principal holds any of several required permissions', () => {
    expect(run({ permission: ['admin.config', 'application.read'] }, MEMBER)).toBe(true);
  });

  it('redirects to the dashboard and toasts when the permission is missing', () => {
    const toast = TestBed.inject(ToastService);
    const toastSpy = jest.spyOn(toast, 'error');
    const result = run({ permission: 'admin.config' }, MEMBER);
    expect(result).toBeInstanceOf(UrlTree);
    expect((result as UrlTree).toString()).toBe('/dashboard');
    expect(toastSpy).toHaveBeenCalled();
  });
});
