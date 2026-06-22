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
import { type Observable } from 'rxjs';
import { homeRedirectGuard } from './home-redirect.guard';
import { USE_MOCK_API } from '../api/api.config';
import type { Principal } from '../api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: [],
  groups: [],
};

describe('homeRedirectGuard', () => {
  let http: HttpTestingController;

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
  });

  afterEach(() => http.verify());

  /** Führt den Guard aus, flusht den `/me`-Probe und liefert das Ergebnis. */
  function run(principal: Principal | null): boolean | UrlTree {
    let result!: boolean | UrlTree;
    TestBed.runInInjectionContext(() => {
      const out = homeRedirectGuard(
        {} as unknown as ActivatedRouteSnapshot,
        {} as RouterStateSnapshot,
      );
      (out as Observable<boolean | UrlTree>).subscribe((r) => (result = r));
    });
    http
      .expectOne('/api/auth/me')
      .flush(principal, principal ? {} : { status: 401, statusText: 'Unauthorized' });
    return result;
  }

  it('redirects an authenticated visitor to /dashboard', () => {
    const result = run(MEMBER);
    expect(result).toBeInstanceOf(UrlTree);
    expect((result as UrlTree).toString()).toBe('/dashboard');
  });

  it('lets an anonymous visitor stay on the public landing page', () => {
    expect(run(null)).toBe(true);
  });
});
