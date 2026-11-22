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
import { FeatureService } from '../features/feature.service';
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

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  /** Runs the guard, flushes the `/me` probe and returns the result. */
  async function run(principal: Principal | null): Promise<boolean | UrlTree> {
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
    await Promise.resolve();
    await Promise.resolve();
    return result;
  }

  it('redirects an authenticated visitor to /activity', async () => {
    TestBed.inject(FeatureService).apply({});
    const result = await run(MEMBER);
    expect(result).toBeInstanceOf(UrlTree);
    expect((result as UrlTree).toString()).toBe('/activity');
  });

  /** Spec 001300: while `Aktivität` is off, the start page is the Anträge. */
  it('redirects to /applications while the activity is off', async () => {
    TestBed.inject(FeatureService).apply({ activity: false });
    const result = await run(MEMBER);
    expect((result as UrlTree).toString()).toBe('/applications');
  });

  it('lets an anonymous visitor stay on the public landing page', async () => {
    expect(await run(null)).toBe(true);
  });
});
