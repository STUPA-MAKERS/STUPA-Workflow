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

  it('handleUnauthorized re-authenticates only when a principal was present', () => {
    auth.handleUnauthorized();
    expect(assign).not.toHaveBeenCalled();

    auth.ensureLoaded().subscribe();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    auth.handleUnauthorized();

    expect(auth.isAuthenticated()).toBe(false);
    expect(assign).toHaveBeenCalledWith('/api/auth/login');
  });

  it('persists the applicant token to sessionStorage', () => {
    auth.setApplicantToken('tok-123');
    expect(auth.applicantToken()).toBe('tok-123');
    expect(sessionStorage.getItem('ap.applicantToken')).toBe('tok-123');
    auth.setApplicantToken(null);
    expect(sessionStorage.getItem('ap.applicantToken')).toBeNull();
  });
});
